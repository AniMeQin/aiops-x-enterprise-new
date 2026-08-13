package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/aiops-x/enterprise/edge-agent/internal/agent"
	"github.com/aiops-x/enterprise/edge-agent/internal/config"
)

const version = "0.1.0"

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg, err := config.FromEnvironment()
	if err != nil {
		logger.Error("invalid configuration", "error", err)
		os.Exit(2)
	}

	server, err := agent.NewServer(cfg, version, logger)
	if err != nil {
		logger.Error("agent initialization failed", "error", err)
		os.Exit(2)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	server.RunControlPlane(ctx)

	errCh := make(chan error, 1)
	go func() {
		errCh <- server.ListenAndServe()
	}()

	logger.Info("edge agent started", "listen", cfg.ListenAddress, "version", version)
	select {
	case <-ctx.Done():
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			logger.Error("agent shutdown failed", "error", err)
		}
	case err := <-errCh:
		if !errors.Is(err, http.ErrServerClosed) {
			logger.Error("agent server stopped", "error", err)
			os.Exit(1)
		}
	}
}
