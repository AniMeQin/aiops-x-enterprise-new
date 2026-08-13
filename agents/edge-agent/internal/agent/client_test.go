package agent

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"log/slog"
	"math/big"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/aiops-x/enterprise/edge-agent/internal/config"
	"github.com/aiops-x/enterprise/edge-agent/internal/hostinfo"
)

func TestInvalidSignatureAndExpiredTaskNeverExecuteAction(t *testing.T) {
	client, privateKey := testClient(t, nil)

	invalid := signedEnvelope(t, privateKey, "invalid", time.Now().Add(time.Minute))
	invalid.Signature = base64.StdEncoding.EncodeToString([]byte("not-a-signature"))
	if _, err := client.verifyTask(invalid); err == nil {
		t.Fatal("expected invalid signature to be rejected")
	}

	expired := signedEnvelope(t, privateKey, "expired", time.Now().Add(-time.Minute))
	verified, err := client.verifyTask(expired)
	if err != nil {
		t.Fatalf("verify expired envelope: %v", err)
	}
	if !time.Now().After(verified.ExpiresAt) {
		t.Fatal("expected task to be expired")
	}
}

func TestEnrollmentCreatesAndPersistsAuthenticatedIdentity(t *testing.T) {
	caKey, caCertificate, caPEM := testCertificateAuthority(t)
	_, taskCertificate := signingIdentity(t)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/api/v1/agents/enroll" {
			http.Error(w, "unexpected request", http.StatusNotFound)
			return
		}
		var payload struct {
			RegistrationToken string `json:"registration_token"`
			CSRPEM            string `json:"csr_pem"`
		}
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil ||
			payload.RegistrationToken != "one-time-enrollment-token" {
			http.Error(w, "invalid enrollment", http.StatusBadRequest)
			return
		}
		certificatePEM, expiresAt, err := issueTestCSR(
			payload.CSRPEM,
			"agent-enrollment-test",
			time.Now().Add(24*time.Hour),
			caKey,
			caCertificate,
		)
		if err != nil {
			http.Error(w, "invalid CSR", http.StatusUnprocessableEntity)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(enrollmentResponse{
			AgentID:                   "agent-enrollment-test",
			CertificatePEM:            certificatePEM,
			CACertificatePEM:          caPEM,
			TaskSigningCertificatePEM: taskCertificate,
			CertificateNotAfter:       expiresAt,
		})
	}))
	defer server.Close()

	stateDirectory := t.TempDir()
	client := &Client{
		cfg: config.Config{
			ControlPlaneURL:   server.URL,
			RegistrationToken: "one-time-enrollment-token",
			StateDirectory:    stateDirectory,
			AllowInsecure:     true,
		},
		version: "test",
		host: hostinfo.Capabilities{
			Hostname: "enrollment-host",
			OS:       "linux",
			Arch:     "amd64",
			Actions:  []string{"system.disk_usage"},
		},
		logger: slog.New(slog.NewTextHandler(io.Discard, nil)),
		ledger: newTaskLedger(),
	}
	if err := client.enroll(context.Background()); err != nil {
		t.Fatalf("enroll Agent: %v", err)
	}
	if !client.Registered() {
		t.Fatal("Agent was not marked as registered")
	}
	stored, err := loadIdentity(filepath.Join(stateDirectory, "identity.json"))
	if err != nil {
		t.Fatalf("load enrollment identity: %v", err)
	}
	if stored.AgentID != "agent-enrollment-test" || stored.PrivateKeyPEM == "" {
		t.Fatal("enrollment identity was incomplete")
	}
	if _, activeClient := client.connectionSnapshot(); activeClient == nil {
		t.Fatal("authenticated client was not activated")
	}
}

func TestTaskResultRetriesAfterDisconnectAndDuplicateTaskIsIdempotent(t *testing.T) {
	var resultRequests atomic.Int32
	disconnected := atomic.Bool{}
	disconnected.Store(true)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if disconnected.Load() {
			http.Error(w, "temporary outage", http.StatusServiceUnavailable)
			return
		}
		resultRequests.Add(1)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client, privateKey := testClient(t, server.Client())
	client.cfg.ControlPlaneURL = server.URL
	envelope := signedEnvelope(t, privateKey, "task-retry-1", time.Now().Add(time.Minute))
	if err := client.executeTask(context.Background(), envelope); err == nil {
		t.Fatal("expected first result upload to fail")
	}
	if len(client.ledger.PendingResults) != 1 {
		t.Fatalf("pending results = %d", len(client.ledger.PendingResults))
	}

	disconnected.Store(false)
	if err := client.flushPendingResults(context.Background()); err != nil {
		t.Fatalf("flush pending result: %v", err)
	}
	if resultRequests.Load() != 1 || len(client.ledger.PendingResults) != 0 {
		t.Fatalf("unexpected replay state: requests=%d pending=%d", resultRequests.Load(), len(client.ledger.PendingResults))
	}
	if err := client.executeTask(context.Background(), envelope); err != nil {
		t.Fatalf("duplicate task should be ignored: %v", err)
	}
	if resultRequests.Load() != 1 {
		t.Fatalf("duplicate task re-posted result: %d", resultRequests.Load())
	}

	reloaded, err := loadTaskLedger(client.ledgerPath)
	if err != nil {
		t.Fatalf("reload task ledger: %v", err)
	}
	if _, ok := reloaded.CompletedTaskIDs[envelope.TaskID]; !ok {
		t.Fatal("completed task was not persisted")
	}
}

func TestCertificateRenewalPersistsPendingKeyAndRetriesSameCSR(t *testing.T) {
	caKey, caCertificate, caPEM := testCertificateAuthority(t)
	currentIdentity := testAgentIdentity(
		t,
		"agent-renewal-test",
		time.Now().Add(30*time.Minute),
		caKey,
		caCertificate,
		caPEM,
	)
	var requestCount atomic.Int32
	var csrMu sync.Mutex
	requestedCSRs := make([]string, 0, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost ||
			r.URL.Path != "/api/v1/agents/agent-renewal-test/certificate/renew" {
			http.Error(w, "unexpected request", http.StatusNotFound)
			return
		}
		var payload certificateRenewalRequest
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			http.Error(w, "invalid request", http.StatusBadRequest)
			return
		}
		csrMu.Lock()
		requestedCSRs = append(requestedCSRs, payload.CSRPEM)
		csrMu.Unlock()
		if requestCount.Add(1) == 1 {
			http.Error(w, "temporary outage", http.StatusServiceUnavailable)
			return
		}
		certificatePEM, expiresAt, err := issueTestCSR(
			payload.CSRPEM,
			currentIdentity.AgentID,
			time.Now().Add(24*time.Hour),
			caKey,
			caCertificate,
		)
		if err != nil {
			http.Error(w, "invalid CSR", http.StatusUnprocessableEntity)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(certificateRenewalResponse{
			AgentID:                   currentIdentity.AgentID,
			CertificatePEM:            certificatePEM,
			CACertificatePEM:          caPEM,
			TaskSigningCertificatePEM: currentIdentity.TaskCertificatePEM,
			CertificateNotAfter:       expiresAt,
		})
	}))
	defer server.Close()

	stateDirectory := t.TempDir()
	client := &Client{
		cfg: config.Config{
			ControlPlaneURL:        server.URL,
			StateDirectory:         stateDirectory,
			AllowInsecure:          true,
			CertificateRenewBefore: time.Hour,
		},
		logger:   slog.New(slog.NewTextHandler(io.Discard, nil)),
		identity: currentIdentity,
		http:     server.Client(),
		ledger:   newTaskLedger(),
	}

	if err := client.renewCertificateIfNeeded(context.Background()); err == nil {
		t.Fatal("expected the first renewal attempt to fail")
	}
	pendingIdentity, err := loadIdentity(filepath.Join(stateDirectory, "identity.json"))
	if err != nil {
		t.Fatalf("load pending identity: %v", err)
	}
	if pendingIdentity.PendingRenewal == nil {
		t.Fatal("pending renewal key was not persisted")
	}
	pendingPrivateKey := pendingIdentity.PendingRenewal.PrivateKeyPEM

	if err := client.renewCertificateIfNeeded(context.Background()); err != nil {
		t.Fatalf("retry certificate renewal: %v", err)
	}
	csrMu.Lock()
	if len(requestedCSRs) != 2 || requestedCSRs[0] != requestedCSRs[1] {
		t.Fatalf("renewal did not retry the persisted CSR: %d requests", len(requestedCSRs))
	}
	csrMu.Unlock()

	renewed, activeClient := client.connectionSnapshot()
	if renewed.PendingRenewal != nil {
		t.Fatal("pending renewal was not cleared")
	}
	if renewed.PrivateKeyPEM != pendingPrivateKey || renewed.PrivateKeyPEM == currentIdentity.PrivateKeyPEM {
		t.Fatal("renewed certificate did not activate the pending private key")
	}
	if activeClient == nil || !renewed.CertificateNotAfter.After(time.Now().Add(23*time.Hour)) {
		t.Fatal("renewed identity was not activated")
	}
	stored, err := loadIdentity(filepath.Join(stateDirectory, "identity.json"))
	if err != nil {
		t.Fatalf("load renewed identity: %v", err)
	}
	if stored.PrivateKeyPEM != renewed.PrivateKeyPEM || stored.PendingRenewal != nil {
		t.Fatal("renewed identity was not stored atomically")
	}
	info, err := filepath.Glob(filepath.Join(stateDirectory, "identity.json"))
	if err != nil || len(info) != 1 {
		t.Fatal("identity file was not written")
	}
	fileInfo, err := os.Stat(info[0])
	if err != nil {
		t.Fatal(err)
	}
	if fileInfo.Mode().Perm() != 0o600 {
		t.Fatalf("identity mode = %o", fileInfo.Mode().Perm())
	}

	if err := client.renewCertificateIfNeeded(context.Background()); err != nil {
		t.Fatalf("renewal outside the window should be a no-op: %v", err)
	}
	if requestCount.Load() != 2 {
		t.Fatalf("unexpected early renewal request count: %d", requestCount.Load())
	}
}

func testClient(t *testing.T, httpClient *http.Client) (*Client, *rsa.PrivateKey) {
	t.Helper()
	privateKey, certificate := signingIdentity(t)
	stateDirectory := t.TempDir()
	client := &Client{
		cfg:        config.Config{StateDirectory: stateDirectory},
		host:       hostinfo.Capabilities{Actions: []string{"system.disk_usage"}},
		logger:     slog.New(slog.NewTextHandler(io.Discard, nil)),
		identity:   identity{AgentID: "agent-test", TaskCertificatePEM: certificate},
		http:       httpClient,
		ledger:     newTaskLedger(),
		ledgerPath: filepath.Join(stateDirectory, "task-ledger.json"),
	}
	return client, privateKey
}

func signingIdentity(t *testing.T) (*rsa.PrivateKey, string) {
	t.Helper()
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: newSerial(t),
		Subject:      pkix.Name{CommonName: "test-task-signing"},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     time.Now().Add(time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &privateKey.PublicKey, privateKey)
	if err != nil {
		t.Fatal(err)
	}
	return privateKey, string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der}))
}

func signedEnvelope(t *testing.T, privateKey *rsa.PrivateKey, taskID string, expiresAt time.Time) taskEnvelope {
	t.Helper()
	payload, err := json.Marshal(signedTask{
		TaskID: taskID, ActionID: "system.disk_usage", ExpiresAt: expiresAt,
		Parameters: map[string]any{"paths": []any{"/"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(payload)
	signature, err := rsa.SignPSS(rand.Reader, privateKey, crypto.SHA256, digest[:], nil)
	if err != nil {
		t.Fatal(err)
	}
	return taskEnvelope{
		TaskID: taskID, SigningPayload: string(payload),
		Signature: base64.StdEncoding.EncodeToString(signature), SignatureAlgorithm: "x509-sha256",
	}
}

func newSerial(t *testing.T) *big.Int {
	t.Helper()
	limit := new(big.Int).Lsh(big.NewInt(1), 128)
	serial, err := rand.Int(rand.Reader, limit)
	if err != nil {
		t.Fatal(err)
	}
	return serial
}

func testCertificateAuthority(t *testing.T) (*rsa.PrivateKey, *x509.Certificate, string) {
	t.Helper()
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber:          newSerial(t),
		Subject:               pkix.Name{CommonName: "Agent Renewal Test CA"},
		NotBefore:             time.Now().Add(-time.Minute),
		NotAfter:              time.Now().Add(48 * time.Hour),
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageDigitalSignature,
		BasicConstraintsValid: true,
		IsCA:                  true,
	}
	der, err := x509.CreateCertificate(
		rand.Reader,
		template,
		template,
		&privateKey.PublicKey,
		privateKey,
	)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return privateKey, certificate, string(pem.EncodeToMemory(&pem.Block{
		Type: "CERTIFICATE", Bytes: der,
	}))
}

func testAgentIdentity(
	t *testing.T,
	agentID string,
	notAfter time.Time,
	caKey *rsa.PrivateKey,
	caCertificate *x509.Certificate,
	caPEM string,
) identity {
	t.Helper()
	privateKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{
		SerialNumber: newSerial(t),
		Subject:      pkix.Name{CommonName: "aiops-x-agent-" + agentID},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     notAfter,
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	der, err := x509.CreateCertificate(
		rand.Reader,
		template,
		caCertificate,
		&privateKey.PublicKey,
		caKey,
	)
	if err != nil {
		t.Fatal(err)
	}
	privateKeyDER := x509.MarshalPKCS1PrivateKey(privateKey)
	_, taskCertificate := signingIdentity(t)
	return identity{
		AgentID:             agentID,
		CertificatePEM:      string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})),
		PrivateKeyPEM:       string(pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: privateKeyDER})),
		CACertificatePEM:    caPEM,
		TaskCertificatePEM:  taskCertificate,
		CertificateNotAfter: notAfter.UTC(),
	}
}

func issueTestCSR(
	csrPEM string,
	agentID string,
	notAfter time.Time,
	caKey *rsa.PrivateKey,
	caCertificate *x509.Certificate,
) (string, time.Time, error) {
	block, _ := pem.Decode([]byte(csrPEM))
	if block == nil || block.Type != "CERTIFICATE REQUEST" {
		return "", time.Time{}, fmt.Errorf("invalid CSR PEM")
	}
	csr, err := x509.ParseCertificateRequest(block.Bytes)
	if err != nil || csr.CheckSignature() != nil {
		return "", time.Time{}, fmt.Errorf("invalid CSR signature")
	}
	template := &x509.Certificate{
		SerialNumber: new(big.Int).SetInt64(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: "aiops-x-agent-" + agentID},
		NotBefore:    time.Now().Add(-time.Minute),
		NotAfter:     notAfter,
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	der, err := x509.CreateCertificate(
		rand.Reader,
		template,
		caCertificate,
		csr.PublicKey,
		caKey,
	)
	if err != nil {
		return "", time.Time{}, err
	}
	return string(pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})),
		notAfter.UTC(), nil
}
