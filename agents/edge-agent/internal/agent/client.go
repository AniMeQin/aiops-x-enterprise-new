package agent

import (
	"bytes"
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/aiops-x/enterprise/edge-agent/internal/actions"
	"github.com/aiops-x/enterprise/edge-agent/internal/config"
	"github.com/aiops-x/enterprise/edge-agent/internal/hostinfo"
)

const maxResponseBytes = 128 * 1024

type identity struct {
	AgentID             string          `json:"agent_id"`
	CertificatePEM      string          `json:"certificate_pem"`
	PrivateKeyPEM       string          `json:"private_key_pem"`
	CACertificatePEM    string          `json:"ca_certificate_pem"`
	TaskCertificatePEM  string          `json:"task_signing_certificate_pem"`
	CertificateNotAfter time.Time       `json:"certificate_not_after"`
	PendingRenewal      *pendingRenewal `json:"pending_renewal,omitempty"`
}

type pendingRenewal struct {
	PrivateKeyPEM string `json:"private_key_pem"`
	CSRPEM        string `json:"csr_pem"`
}

type enrollmentResponse struct {
	AgentID                   string    `json:"agent_id"`
	CertificatePEM            string    `json:"certificate_pem"`
	CACertificatePEM          string    `json:"ca_certificate_pem"`
	TaskSigningCertificatePEM string    `json:"task_signing_certificate_pem"`
	CertificateNotAfter       time.Time `json:"certificate_not_after"`
}

type certificateRenewalRequest struct {
	CSRPEM string `json:"csr_pem"`
}

type certificateRenewalResponse struct {
	AgentID                   string    `json:"agent_id"`
	CertificatePEM            string    `json:"certificate_pem"`
	CACertificatePEM          string    `json:"ca_certificate_pem"`
	TaskSigningCertificatePEM string    `json:"task_signing_certificate_pem"`
	CertificateNotAfter       time.Time `json:"certificate_not_after"`
}

type heartbeatRequest struct {
	Hostname     string         `json:"hostname"`
	Platform     string         `json:"platform"`
	Architecture string         `json:"architecture"`
	Version      string         `json:"version"`
	HealthStatus string         `json:"health_status"`
	Capabilities map[string]any `json:"capabilities"`
}

type taskEnvelope struct {
	TaskID             string `json:"task_id"`
	SigningPayload     string `json:"signing_payload"`
	Signature          string `json:"signature"`
	SignatureAlgorithm string `json:"signature_algorithm"`
}

type signedTask struct {
	ActionID   string         `json:"action_id"`
	ExpiresAt  time.Time      `json:"expires_at"`
	Parameters map[string]any `json:"parameters"`
	TaskID     string         `json:"task_id"`
}

type taskResult struct {
	Status          string         `json:"status"`
	DurationMS      int64          `json:"duration_ms"`
	SanitizedOutput map[string]any `json:"sanitized_output"`
	ErrorCode       string         `json:"error_code,omitempty"`
	ErrorMessage    string         `json:"error_message,omitempty"`
}

type taskLedger struct {
	CompletedTaskIDs map[string]time.Time  `json:"completed_task_ids"`
	PendingResults   map[string]taskResult `json:"pending_results"`
}

type Client struct {
	cfg        config.Config
	version    string
	host       hostinfo.Capabilities
	logger     *slog.Logger
	mu         sync.RWMutex
	renewMu    sync.Mutex
	identity   identity
	http       *http.Client
	ledger     taskLedger
	ledgerPath string
}

func NewClient(cfg config.Config, version string, host hostinfo.Capabilities, logger *slog.Logger) (*Client, error) {
	ledgerPath := filepath.Join(cfg.StateDirectory, "task-ledger.json")
	ledger, err := loadTaskLedger(ledgerPath)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("load task ledger: %w", err)
	}
	if errors.Is(err, os.ErrNotExist) {
		ledger = newTaskLedger()
	}
	client := &Client{cfg: cfg, version: version, host: host, logger: logger, ledger: ledger, ledgerPath: ledgerPath}
	loaded, err := loadIdentity(filepath.Join(cfg.StateDirectory, "identity.json"))
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("load Agent identity: %w", err)
	}
	if err == nil {
		client.identity = loaded
		client.http, err = authenticatedHTTPClient(cfg, loaded)
		if err != nil {
			return nil, err
		}
	}
	return client, nil
}

func (c *Client) Registered() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.identity.AgentID != ""
}

func (c *Client) Readiness() (bool, string) {
	current, _ := c.connectionSnapshot()
	if current.AgentID == "" {
		return false, "registration_required"
	}
	certificate, err := parseIdentityCertificate(current)
	if err != nil {
		return false, "certificate_invalid"
	}
	now := time.Now().UTC()
	if certificate.NotBefore.After(now) {
		return false, "certificate_invalid"
	}
	if !certificate.NotAfter.After(now) {
		return false, "certificate_expired"
	}
	return true, "ok"
}

func (c *Client) Run(ctx context.Context) {
	if c.cfg.ControlPlaneURL == "" {
		return
	}
	if !c.Registered() {
		if c.cfg.RegistrationToken == "" {
			c.logger.Warn("Agent enrollment required; no registration token configured")
			return
		}
		if err := c.enroll(ctx); err != nil {
			c.logger.Error("Agent enrollment failed", "error", err)
			return
		}
	}
	if err := c.renewCertificateIfNeeded(ctx); err != nil {
		c.logger.Warn("Agent certificate renewal deferred", "error", err)
	}
	go c.certificateRenewalLoop(ctx)
	go c.heartbeatLoop(ctx)
	go c.taskLoop(ctx)
}

func (c *Client) enroll(ctx context.Context) error {
	privateKeyPEM, csrPEM, err := generateKeyAndCSR("aiops-x-enrollment")
	if err != nil {
		return err
	}
	payload := map[string]any{
		"registration_token": c.cfg.RegistrationToken,
		"name":               c.host.Hostname,
		"hostname":           c.host.Hostname,
		"platform":           c.host.OS,
		"architecture":       c.host.Arch,
		"version":            c.version,
		"csr_pem":            csrPEM,
		"capabilities":       map[string]any{"actions": c.host.Actions},
	}
	var response enrollmentResponse
	if err := c.request(ctx, enrollmentHTTPClient(c.cfg), http.MethodPost, "/api/v1/agents/enroll", payload, &response); err != nil {
		return err
	}
	if response.AgentID == "" {
		return fmt.Errorf("enrollment response is missing Agent identity")
	}
	newIdentity := identity{
		AgentID:             response.AgentID,
		CertificatePEM:      response.CertificatePEM,
		PrivateKeyPEM:       privateKeyPEM,
		CACertificatePEM:    response.CACertificatePEM,
		TaskCertificatePEM:  response.TaskSigningCertificatePEM,
		CertificateNotAfter: response.CertificateNotAfter,
	}
	authenticatedClient, err := authenticatedHTTPClient(c.cfg, newIdentity)
	if err != nil {
		return err
	}
	newIdentity.CertificateNotAfter, err = validateIssuedIdentity(newIdentity)
	if err != nil {
		return err
	}
	if err := saveIdentity(filepath.Join(c.cfg.StateDirectory, "identity.json"), newIdentity); err != nil {
		return err
	}
	c.mu.Lock()
	c.identity = newIdentity
	c.http = authenticatedClient
	c.mu.Unlock()
	c.logger.Info("Agent enrolled", "agent_id", newIdentity.AgentID)
	return nil
}

func (c *Client) certificateRenewalLoop(ctx context.Context) {
	c.withBackoff(ctx, 5*time.Minute, func(requestCtx context.Context) error {
		return c.renewCertificateIfNeeded(requestCtx)
	})
}

func (c *Client) renewCertificateIfNeeded(ctx context.Context) error {
	c.renewMu.Lock()
	defer c.renewMu.Unlock()

	current, client := c.connectionSnapshot()
	expiresAt, err := identityCertificateNotAfter(current)
	if err != nil {
		return err
	}
	now := time.Now().UTC()
	if !expiresAt.After(now) {
		return fmt.Errorf("agent certificate expired; a new registration token is required")
	}
	if expiresAt.After(now.Add(c.cfg.CertificateRenewBefore)) {
		return nil
	}

	if current.PendingRenewal == nil {
		privateKeyPEM, csrPEM, generationErr := generateKeyAndCSR(
			"aiops-x-agent-" + current.AgentID,
		)
		if generationErr != nil {
			return generationErr
		}
		current.PendingRenewal = &pendingRenewal{
			PrivateKeyPEM: privateKeyPEM,
			CSRPEM:        csrPEM,
		}
		if err := saveIdentity(filepath.Join(c.cfg.StateDirectory, "identity.json"), current); err != nil {
			return fmt.Errorf("persist pending certificate renewal: %w", err)
		}
		c.mu.Lock()
		c.identity = current
		c.mu.Unlock()
	}

	var response certificateRenewalResponse
	path := "/api/v1/agents/" + current.AgentID + "/certificate/renew"
	if err := c.request(
		ctx,
		client,
		http.MethodPost,
		path,
		certificateRenewalRequest{CSRPEM: current.PendingRenewal.CSRPEM},
		&response,
	); err != nil {
		return err
	}
	if response.AgentID != current.AgentID {
		return fmt.Errorf("certificate renewal identity mismatch")
	}
	newIdentity := identity{
		AgentID:             current.AgentID,
		CertificatePEM:      response.CertificatePEM,
		PrivateKeyPEM:       current.PendingRenewal.PrivateKeyPEM,
		CACertificatePEM:    response.CACertificatePEM,
		TaskCertificatePEM:  response.TaskSigningCertificatePEM,
		CertificateNotAfter: response.CertificateNotAfter,
	}
	authenticatedClient, err := authenticatedHTTPClient(c.cfg, newIdentity)
	if err != nil {
		return err
	}
	newIdentity.CertificateNotAfter, err = validateIssuedIdentity(newIdentity)
	if err != nil {
		return err
	}
	if err := saveIdentity(filepath.Join(c.cfg.StateDirectory, "identity.json"), newIdentity); err != nil {
		return fmt.Errorf("persist renewed Agent identity: %w", err)
	}
	c.mu.Lock()
	c.identity = newIdentity
	c.http = authenticatedClient
	c.mu.Unlock()
	if client != nil {
		client.CloseIdleConnections()
	}
	c.logger.Info("Agent certificate renewed", "agent_id", newIdentity.AgentID,
		"expires_at", newIdentity.CertificateNotAfter)
	return nil
}

func (c *Client) connectionSnapshot() (identity, *http.Client) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.identity, c.http
}

func (c *Client) heartbeatLoop(ctx context.Context) {
	c.withBackoff(ctx, c.cfg.HeartbeatInterval, func(requestCtx context.Context) error {
		current, client := c.connectionSnapshot()
		payload := heartbeatRequest{
			Hostname: c.host.Hostname, Platform: c.host.OS, Architecture: c.host.Arch,
			Version: c.version, HealthStatus: "healthy",
			Capabilities: map[string]any{"actions": c.host.Actions},
		}
		return c.request(requestCtx, client, http.MethodPost, "/api/v1/agents/"+current.AgentID+"/heartbeat", payload, nil)
	})
}

func (c *Client) taskLoop(ctx context.Context) {
	c.withBackoff(ctx, c.cfg.TaskPollInterval, func(requestCtx context.Context) error {
		if err := c.flushPendingResults(requestCtx); err != nil {
			return err
		}
		current, client := c.connectionSnapshot()
		var envelope *taskEnvelope
		if err := c.request(requestCtx, client, http.MethodGet, "/api/v1/agents/"+current.AgentID+"/tasks/next", nil, &envelope); err != nil {
			return err
		}
		if envelope == nil {
			return nil
		}
		return c.executeTask(requestCtx, *envelope)
	})
}

func (c *Client) executeTask(ctx context.Context, envelope taskEnvelope) error {
	c.mu.RLock()
	_, completed := c.ledger.CompletedTaskIDs[envelope.TaskID]
	c.mu.RUnlock()
	if completed {
		return nil
	}
	started := time.Now()
	task, err := c.verifyTask(envelope)
	result := taskResult{Status: "failed", SanitizedOutput: map[string]any{}}
	if err != nil {
		result.ErrorCode = "AGENT_TASK_SIGNATURE_INVALID"
		result.ErrorMessage = "task signature or payload validation failed"
	} else if time.Now().After(task.ExpiresAt) {
		result.ErrorCode = "AGENT_TASK_EXPIRED"
		result.ErrorMessage = "task expired before execution"
	} else if task.ActionID != "system.disk_usage" {
		result.ErrorCode = "AGENT_ACTION_NOT_REGISTERED"
		result.ErrorMessage = "action is not registered"
	} else {
		paths, pathsErr := taskPaths(task.Parameters)
		if pathsErr != nil {
			result.ErrorCode = "AGENT_PARAMETERS_INVALID"
			result.ErrorMessage = pathsErr.Error()
		} else {
			disks, diskErr := actions.DiskUsageForPaths(paths)
			if diskErr != nil {
				result.ErrorCode = "AGENT_ACTION_FAILED"
				result.ErrorMessage = diskErr.Error()
			} else {
				result.Status = "succeeded"
				result.SanitizedOutput = map[string]any{"filesystems": disks}
			}
		}
	}
	result.DurationMS = time.Since(started).Milliseconds()
	if err := c.queueResult(envelope.TaskID, result); err != nil {
		return err
	}
	return c.flushPendingResults(ctx)
}

func (c *Client) queueResult(taskID string, result taskResult) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.ledger.PendingResults[taskID] = result
	return saveTaskLedger(c.ledgerPath, c.ledger)
}

func (c *Client) flushPendingResults(ctx context.Context) error {
	c.mu.RLock()
	pending := make(map[string]taskResult, len(c.ledger.PendingResults))
	for taskID, result := range c.ledger.PendingResults {
		pending[taskID] = result
	}
	c.mu.RUnlock()
	for taskID, result := range pending {
		current, client := c.connectionSnapshot()
		path := "/api/v1/agents/" + current.AgentID + "/tasks/" + taskID + "/result"
		if err := c.request(ctx, client, http.MethodPost, path, result, nil); err != nil {
			return err
		}
		c.mu.Lock()
		delete(c.ledger.PendingResults, taskID)
		c.ledger.CompletedTaskIDs[taskID] = time.Now().UTC()
		pruneCompletedTasks(c.ledger.CompletedTaskIDs, time.Now().UTC().Add(-7*24*time.Hour))
		err := saveTaskLedger(c.ledgerPath, c.ledger)
		c.mu.Unlock()
		if err != nil {
			return err
		}
	}
	return nil
}

func (c *Client) verifyTask(envelope taskEnvelope) (signedTask, error) {
	if envelope.SignatureAlgorithm != "x509-sha256" {
		return signedTask{}, fmt.Errorf("unsupported signature algorithm")
	}
	current, _ := c.connectionSnapshot()
	block, _ := pem.Decode([]byte(current.TaskCertificatePEM))
	if block == nil {
		return signedTask{}, fmt.Errorf("invalid signing certificate")
	}
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return signedTask{}, err
	}
	now := time.Now().UTC()
	if certificate.NotBefore.After(now) || !certificate.NotAfter.After(now) ||
		certificate.KeyUsage&x509.KeyUsageDigitalSignature == 0 {
		return signedTask{}, fmt.Errorf("invalid signing certificate validity or usage")
	}
	publicKey, ok := certificate.PublicKey.(*rsa.PublicKey)
	if !ok {
		return signedTask{}, fmt.Errorf("unsupported signing key")
	}
	signature, err := base64.StdEncoding.DecodeString(envelope.Signature)
	if err != nil {
		return signedTask{}, err
	}
	digest := sha256.Sum256([]byte(envelope.SigningPayload))
	if err := rsa.VerifyPSS(publicKey, crypto.SHA256, digest[:], signature, nil); err != nil {
		return signedTask{}, err
	}
	var task signedTask
	if err := json.Unmarshal([]byte(envelope.SigningPayload), &task); err != nil {
		return signedTask{}, err
	}
	if task.TaskID != envelope.TaskID {
		return signedTask{}, fmt.Errorf("task identity mismatch")
	}
	return task, nil
}

func (c *Client) withBackoff(ctx context.Context, interval time.Duration, operation func(context.Context) error) {
	failures := 0
	for {
		if err := operation(ctx); err != nil {
			failures++
			delay := time.Duration(math.Min(math.Pow(2, float64(failures)), 30)) * time.Second
			c.logger.Warn("control-plane request failed", "error", err, "retry_in", delay)
			if !waitContext(ctx, delay) {
				return
			}
			continue
		}
		failures = 0
		if !waitContext(ctx, interval) {
			return
		}
	}
}

func (c *Client) request(ctx context.Context, client *http.Client, method, path string, payload any, target any) error {
	var body io.Reader
	if payload != nil {
		encoded, err := json.Marshal(payload)
		if err != nil {
			return err
		}
		body = bytes.NewReader(encoded)
	}
	requestCtx, cancel := context.WithTimeout(ctx, 20*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(requestCtx, method, c.cfg.ControlPlaneURL+path, body)
	if err != nil {
		return err
	}
	request.Header.Set("Accept", "application/json")
	if payload != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer func() {
		_ = response.Body.Close()
	}()
	limited := io.LimitReader(response.Body, maxResponseBytes+1)
	responseBody, err := io.ReadAll(limited)
	if err != nil {
		return err
	}
	if len(responseBody) > maxResponseBytes {
		return fmt.Errorf("control-plane response exceeds limit")
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return fmt.Errorf("control-plane HTTP %d", response.StatusCode)
	}
	if target != nil && len(responseBody) > 0 {
		if err := json.Unmarshal(responseBody, target); err != nil {
			return err
		}
	}
	return nil
}

func enrollmentHTTPClient(cfg config.Config) *http.Client {
	roots := x509.NewCertPool()
	if data, err := os.ReadFile(cfg.CACertificatePath); err == nil {
		roots.AppendCertsFromPEM(data)
	}
	return &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{
		MinVersion: tls.VersionTLS12, RootCAs: roots, InsecureSkipVerify: cfg.AllowInsecure, //nolint:gosec // explicit test-only switch
	}}}
}

func authenticatedHTTPClient(cfg config.Config, identity identity) (*http.Client, error) {
	certificate, err := tls.X509KeyPair([]byte(identity.CertificatePEM), []byte(identity.PrivateKeyPEM))
	if err != nil {
		return nil, fmt.Errorf("load Agent certificate: %w", err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM([]byte(identity.CACertificatePEM)) {
		return nil, fmt.Errorf("load Agent CA certificate")
	}
	leaf, err := x509.ParseCertificate(certificate.Certificate[0])
	if err != nil {
		return nil, fmt.Errorf("parse Agent certificate: %w", err)
	}
	intermediates := x509.NewCertPool()
	for _, certificateDER := range certificate.Certificate[1:] {
		intermediate, parseErr := x509.ParseCertificate(certificateDER)
		if parseErr != nil {
			return nil, fmt.Errorf("parse Agent certificate chain: %w", parseErr)
		}
		intermediates.AddCert(intermediate)
	}
	verificationTime := time.Now().UTC()
	if verificationTime.Before(leaf.NotBefore) || !verificationTime.Before(leaf.NotAfter) {
		verificationTime = leaf.NotBefore.Add(time.Second)
	}
	if _, err := leaf.Verify(x509.VerifyOptions{
		Roots:         roots,
		Intermediates: intermediates,
		KeyUsages:     []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
		CurrentTime:   verificationTime,
	}); err != nil {
		return nil, fmt.Errorf("verify Agent certificate chain: %w", err)
	}
	if leaf.Subject.CommonName != "aiops-x-agent-"+identity.AgentID {
		return nil, fmt.Errorf("agent certificate subject mismatch")
	}
	return &http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{
		MinVersion: tls.VersionTLS12, RootCAs: roots, Certificates: []tls.Certificate{certificate},
		InsecureSkipVerify: cfg.AllowInsecure, //nolint:gosec // explicit test-only switch
	}}}, nil
}

func saveIdentity(path string, value identity) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return err
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, encoded, 0o600); err != nil {
		return err
	}
	if err := os.Chmod(temporary, 0o600); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

func loadIdentity(path string) (identity, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return identity{}, err
	}
	var value identity
	if err := json.Unmarshal(data, &value); err != nil {
		return identity{}, err
	}
	if value.AgentID == "" || !strings.Contains(value.PrivateKeyPEM, "PRIVATE KEY") ||
		value.CertificatePEM == "" || value.CACertificatePEM == "" ||
		value.TaskCertificatePEM == "" {
		return identity{}, fmt.Errorf("incomplete identity")
	}
	expiresAt, err := identityCertificateNotAfter(value)
	if err != nil {
		return identity{}, err
	}
	value.CertificateNotAfter = expiresAt
	return value, nil
}

func generateKeyAndCSR(commonName string) (string, string, error) {
	privateKey, err := rsa.GenerateKey(rand.Reader, 3072)
	if err != nil {
		return "", "", fmt.Errorf("generate Agent key: %w", err)
	}
	csrDER, err := x509.CreateCertificateRequest(rand.Reader, &x509.CertificateRequest{
		Subject: pkix.Name{CommonName: commonName},
	}, privateKey)
	if err != nil {
		return "", "", fmt.Errorf("create CSR: %w", err)
	}
	privateKeyDER := x509.MarshalPKCS1PrivateKey(privateKey)
	privateKeyPEM := pem.EncodeToMemory(
		&pem.Block{Type: "RSA PRIVATE KEY", Bytes: privateKeyDER},
	)
	csrPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE REQUEST", Bytes: csrDER})
	return string(privateKeyPEM), string(csrPEM), nil
}

func identityCertificateNotAfter(value identity) (time.Time, error) {
	certificate, err := parseIdentityCertificate(value)
	if err != nil {
		return time.Time{}, err
	}
	return certificate.NotAfter.UTC(), nil
}

func validateIssuedIdentity(value identity) (time.Time, error) {
	certificate, err := parseIdentityCertificate(value)
	if err != nil {
		return time.Time{}, err
	}
	now := time.Now().UTC()
	if certificate.NotBefore.After(now) || !certificate.NotAfter.After(now) {
		return time.Time{}, fmt.Errorf("issued agent certificate is not currently valid")
	}
	return certificate.NotAfter.UTC(), nil
}

func parseIdentityCertificate(value identity) (*x509.Certificate, error) {
	block, _ := pem.Decode([]byte(value.CertificatePEM))
	if block == nil || block.Type != "CERTIFICATE" {
		return nil, fmt.Errorf("invalid agent certificate")
	}
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parse agent certificate: %w", err)
	}
	return certificate, nil
}

func newTaskLedger() taskLedger {
	return taskLedger{
		CompletedTaskIDs: map[string]time.Time{},
		PendingResults:   map[string]taskResult{},
	}
}

func loadTaskLedger(path string) (taskLedger, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return taskLedger{}, err
	}
	value := newTaskLedger()
	if err := json.Unmarshal(data, &value); err != nil {
		return taskLedger{}, err
	}
	if value.CompletedTaskIDs == nil {
		value.CompletedTaskIDs = map[string]time.Time{}
	}
	if value.PendingResults == nil {
		value.PendingResults = map[string]taskResult{}
	}
	return value, nil
}

func saveTaskLedger(path string, value taskLedger) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	encoded, err := json.Marshal(value)
	if err != nil {
		return err
	}
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, encoded, 0o600); err != nil {
		return err
	}
	if err := os.Chmod(temporary, 0o600); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

func pruneCompletedTasks(tasks map[string]time.Time, cutoff time.Time) {
	for taskID, completedAt := range tasks {
		if completedAt.Before(cutoff) {
			delete(tasks, taskID)
		}
	}
}

func taskPaths(parameters map[string]any) ([]string, error) {
	rawPaths, ok := parameters["paths"].([]any)
	if !ok || len(rawPaths) == 0 || len(rawPaths) > 8 {
		return nil, fmt.Errorf("invalid paths")
	}
	paths := make([]string, 0, len(rawPaths))
	for _, value := range rawPaths {
		path, ok := value.(string)
		if !ok || !filepath.IsAbs(path) {
			return nil, fmt.Errorf("invalid absolute path")
		}
		paths = append(paths, path)
	}
	return paths, nil
}

func waitContext(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return false
	case <-timer.C:
		return true
	}
}
