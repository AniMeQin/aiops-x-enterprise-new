package config

import "testing"

func TestControlPlaneRequiresHTTPS(t *testing.T) {
	t.Setenv("AIOPS_CONTROL_PLANE_URL", "http://control-plane.internal")
	t.Setenv("AIOPS_ALLOW_INSECURE", "false")

	_, err := FromEnvironment()
	if err == nil {
		t.Fatal("expected an error for an insecure control-plane URL")
	}
}

func TestDevelopmentCanExplicitlyAllowHTTP(t *testing.T) {
	t.Setenv("AIOPS_CONTROL_PLANE_URL", "http://localhost:8000")
	t.Setenv("AIOPS_ALLOW_INSECURE", "true")

	cfg, err := FromEnvironment()
	if err != nil {
		t.Fatalf("expected development HTTP to be allowed: %v", err)
	}
	if cfg.ControlPlaneURL != "http://localhost:8000" {
		t.Fatalf("unexpected URL: %s", cfg.ControlPlaneURL)
	}
}

func TestCertificateRenewBeforeIsValidated(t *testing.T) {
	t.Setenv("AIOPS_CERTIFICATE_RENEW_BEFORE", "30s")

	_, err := FromEnvironment()
	if err == nil {
		t.Fatal("expected an error for an unsafe certificate renewal interval")
	}
}
