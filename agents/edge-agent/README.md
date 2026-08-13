# AIOps-X Edge Agent

The Edge Agent is an independently deployable Go process. It implements one-time enrollment, a locally generated private key, short-lived mTLS identity, automatic key and certificate rotation, outbound heartbeat and capability reporting, signed task polling with exponential backoff, local identity persistence, and graceful shutdown.

The action registry contains only `system.disk_usage` (R0). It reads filesystem statistics through Go system calls and never accepts arbitrary shell commands. Until enrollment succeeds, readiness reports `registration_required`; an expired identity reports `certificate_expired`, so the Agent never fabricates an online platform state. Completed task IDs and results waiting to be uploaded are persisted in `task-ledger.json` with mode `0600`: a disconnected Agent retries the result after reconnecting and will not execute an already completed task again. Renewal starts six hours before expiry by default. A pending private key and CSR are atomically persisted before the request, and the control plane accepts the previous certificate until its original expiry so a lost renewal response can be retried safely. Server-side offline task delivery policy remains later hardening work.

```bash
export AIOPS_CONTROL_PLANE_URL=https://control-plane.example:8443
export AIOPS_REGISTRATION_TOKEN='<one-time-token>'
export AIOPS_STATE_DIRECTORY=/var/lib/aiops-x
export AIOPS_CA_CERT_PATH=/etc/aiops-x/agent-ca-cert.pem
export AIOPS_CERTIFICATE_RENEW_BEFORE=6h
go run ./agents/edge-agent/cmd/edge-agent
curl http://127.0.0.1:9188/health
curl http://127.0.0.1:9188/ready
```
