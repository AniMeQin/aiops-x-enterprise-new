package agent

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/aiops-x/enterprise/edge-agent/internal/config"
	"github.com/aiops-x/enterprise/edge-agent/internal/hostinfo"
)

func TestUnregisteredAgentIsHealthyButNotReady(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	server, err := NewServer(config.Config{
		ListenAddress: "127.0.0.1:0", StateDirectory: filepath.Join(t.TempDir(), "state"),
	}, "test", logger)
	if err != nil {
		t.Fatalf("new server: %v", err)
	}

	health := httptest.NewRecorder()
	server.httpServer.Handler.ServeHTTP(health, httptest.NewRequest(http.MethodGet, "/health", nil))
	if health.Code != http.StatusOK {
		t.Fatalf("health status = %d", health.Code)
	}

	ready := httptest.NewRecorder()
	server.httpServer.Handler.ServeHTTP(ready, httptest.NewRequest(http.MethodGet, "/ready", nil))
	if ready.Code != http.StatusServiceUnavailable {
		t.Fatalf("ready status = %d", ready.Code)
	}
	if !strings.Contains(ready.Body.String(), "registration_required") {
		t.Fatalf("unexpected ready response: %s", ready.Body.String())
	}
}

func TestExpiredAgentCertificateIsNotReady(t *testing.T) {
	caKey, caCertificate, caPEM := testCertificateAuthority(t)
	expiredIdentity := testAgentIdentity(
		t,
		"expired-agent",
		time.Now().Add(-30*time.Second),
		caKey,
		caCertificate,
		caPEM,
	)
	stateDirectory := t.TempDir()
	if err := saveIdentity(filepath.Join(stateDirectory, "identity.json"), expiredIdentity); err != nil {
		t.Fatalf("save expired identity: %v", err)
	}
	client, err := NewClient(
		config.Config{StateDirectory: stateDirectory, AllowInsecure: true},
		"test",
		hostinfo.Capabilities{},
		slog.New(slog.NewTextHandler(io.Discard, nil)),
	)
	if err != nil {
		t.Fatalf("load expired identity: %v", err)
	}
	server := &Server{
		version: "test",
		client:  client,
	}

	ready := httptest.NewRecorder()
	server.ready(ready, httptest.NewRequest(http.MethodGet, "/ready", nil))
	if ready.Code != http.StatusServiceUnavailable {
		t.Fatalf("ready status = %d", ready.Code)
	}
	if !strings.Contains(ready.Body.String(), "certificate_expired") {
		t.Fatalf("unexpected ready response: %s", ready.Body.String())
	}
}
