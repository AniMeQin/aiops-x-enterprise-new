package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	ListenAddress          string
	ControlPlaneURL        string
	RegistrationToken      string
	StateDirectory         string
	CACertificatePath      string
	AllowInsecure          bool
	HeartbeatInterval      time.Duration
	TaskPollInterval       time.Duration
	CertificateRenewBefore time.Duration
}

func FromEnvironment() (Config, error) {
	allowInsecure, err := strconv.ParseBool(environmentOrDefault("AIOPS_ALLOW_INSECURE", "false"))
	if err != nil {
		return Config{}, fmt.Errorf("AIOPS_ALLOW_INSECURE must be boolean: %w", err)
	}
	heartbeatInterval, err := time.ParseDuration(environmentOrDefault("AIOPS_HEARTBEAT_INTERVAL", "15s"))
	if err != nil || heartbeatInterval < time.Second {
		return Config{}, fmt.Errorf("AIOPS_HEARTBEAT_INTERVAL must be at least 1s")
	}
	taskPollInterval, err := time.ParseDuration(environmentOrDefault("AIOPS_TASK_POLL_INTERVAL", "5s"))
	if err != nil || taskPollInterval < time.Second {
		return Config{}, fmt.Errorf("AIOPS_TASK_POLL_INTERVAL must be at least 1s")
	}
	certificateRenewBefore, err := time.ParseDuration(
		environmentOrDefault("AIOPS_CERTIFICATE_RENEW_BEFORE", "6h"),
	)
	if err != nil || certificateRenewBefore < 5*time.Minute || certificateRenewBefore > 7*24*time.Hour {
		return Config{}, fmt.Errorf("AIOPS_CERTIFICATE_RENEW_BEFORE must be between 5m and 168h")
	}
	cfg := Config{
		ListenAddress:          environmentOrDefault("AIOPS_AGENT_LISTEN", "127.0.0.1:9188"),
		ControlPlaneURL:        strings.TrimRight(strings.TrimSpace(os.Getenv("AIOPS_CONTROL_PLANE_URL")), "/"),
		RegistrationToken:      strings.TrimSpace(os.Getenv("AIOPS_REGISTRATION_TOKEN")),
		StateDirectory:         environmentOrDefault("AIOPS_STATE_DIRECTORY", "/var/lib/aiops-x"),
		CACertificatePath:      environmentOrDefault("AIOPS_CA_CERT_PATH", "/etc/aiops-x/ca-cert.pem"),
		AllowInsecure:          allowInsecure,
		HeartbeatInterval:      heartbeatInterval,
		TaskPollInterval:       taskPollInterval,
		CertificateRenewBefore: certificateRenewBefore,
	}
	if cfg.ListenAddress == "" || cfg.StateDirectory == "" {
		return Config{}, fmt.Errorf("agent listen address and state directory must not be empty")
	}
	if cfg.ControlPlaneURL != "" {
		parsed, parseErr := url.ParseRequestURI(cfg.ControlPlaneURL)
		if parseErr != nil {
			return Config{}, fmt.Errorf("AIOPS_CONTROL_PLANE_URL is invalid: %w", parseErr)
		}
		if parsed.Scheme != "https" && !cfg.AllowInsecure {
			return Config{}, fmt.Errorf("AIOPS_CONTROL_PLANE_URL must use HTTPS")
		}
	}
	return cfg, nil
}

func environmentOrDefault(name, fallback string) string {
	if value, exists := os.LookupEnv(name); exists {
		return strings.TrimSpace(value)
	}
	return fallback
}
