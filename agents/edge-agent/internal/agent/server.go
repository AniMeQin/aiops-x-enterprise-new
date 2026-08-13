package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/aiops-x/enterprise/edge-agent/internal/config"
	"github.com/aiops-x/enterprise/edge-agent/internal/hostinfo"
)

type Server struct {
	httpServer *http.Server
	version    string
	client     *Client
	requests   atomic.Uint64
	host       hostinfo.Capabilities
}

func NewServer(cfg config.Config, version string, logger *slog.Logger) (*Server, error) {
	host, err := hostinfo.Collect()
	if err != nil {
		return nil, fmt.Errorf("collect host capabilities: %w", err)
	}
	server := &Server{
		version: version,
		host:    host,
	}
	client, err := NewClient(cfg, version, host, logger)
	if err != nil {
		return nil, fmt.Errorf("initialize control-plane client: %w", err)
	}
	server.client = client
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", server.health)
	mux.HandleFunc("GET /ready", server.ready)
	mux.HandleFunc("GET /metrics", server.metrics)
	mux.HandleFunc("GET /capabilities", server.capabilities)
	server.httpServer = &http.Server{
		Addr:              cfg.ListenAddress,
		Handler:           requestLogMiddleware(logger, &server.requests, mux),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       60 * time.Second,
	}
	return server, nil
}

func (s *Server) ListenAndServe() error {
	return s.httpServer.ListenAndServe()
}

func (s *Server) Shutdown(ctx context.Context) error {
	return s.httpServer.Shutdown(ctx)
}

func (s *Server) RunControlPlane(ctx context.Context) {
	s.client.Run(ctx)
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok", "service": "aiops-x-edge-agent", "version": s.version,
	})
}

func (s *Server) ready(w http.ResponseWriter, _ *http.Request) {
	ready, status := s.client.Readiness()
	if !ready {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"status": status, "service": "aiops-x-edge-agent",
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok", "service": "aiops-x-edge-agent",
	})
}

func (s *Server) capabilities(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, s.host)
}

func (s *Server) metrics(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	_, _ = fmt.Fprintf(
		w,
		"# HELP aiops_x_agent_http_requests_total Total local health endpoint requests.\n"+
			"# TYPE aiops_x_agent_http_requests_total counter\n"+
			"aiops_x_agent_http_requests_total %d\n",
		s.requests.Load(),
	)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func requestLogMiddleware(logger *slog.Logger, counter *atomic.Uint64, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		counter.Add(1)
		startedAt := time.Now()
		next.ServeHTTP(w, r)
		logger.Info(
			"local agent request",
			"method", r.Method,
			"path", r.URL.Path,
			"duration_ms", time.Since(startedAt).Milliseconds(),
		)
	})
}
