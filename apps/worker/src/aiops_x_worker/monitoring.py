import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from aiops_x_api.core.config import get_settings
from celery.signals import worker_ready, worker_shutdown
from prometheus_client import CONTENT_TYPE_LATEST, Gauge, generate_latest
from redis import Redis
from redis.exceptions import RedisError

WORKER_READY = Gauge("aiops_x_worker_ready", "Celery worker readiness state.")
CELERY_QUEUE_DEPTH = Gauge("aiops_x_celery_queue_depth", "Pending tasks in the Celery queue.")
_ready = False
_server: ThreadingHTTPServer | None = None


@worker_ready.connect  # type: ignore[untyped-decorator]
def mark_ready(**_: object) -> None:
    global _ready
    _ready = True
    WORKER_READY.set(1)


@worker_shutdown.connect  # type: ignore[untyped-decorator]
def mark_not_ready(**_: object) -> None:
    global _ready
    _ready = False
    WORKER_READY.set(0)


class MonitorHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler interface
        if self.path == "/health":
            self._json(200, {"status": "ok", "service": "aiops-x-worker"})
            return
        if self.path == "/ready":
            self._json(
                200 if _ready else 503,
                {
                    "status": "ok" if _ready else "unavailable",
                    "service": "aiops-x-worker",
                },
            )
            return
        if self.path == "/metrics":
            _update_queue_depth()
            body = generate_latest()
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json(404, {"status": "not_found"})

    def log_message(self, _: str, *__: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, str]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_monitoring_server() -> None:
    global _server
    port = int(os.getenv("AIOPS_WORKER_MONITOR_PORT", "0"))
    if port <= 0 or _server is not None:
        return
    _server = ThreadingHTTPServer(("0.0.0.0", port), MonitorHandler)  # noqa: S104
    threading.Thread(target=_server.serve_forever, daemon=True, name="worker-monitor").start()


def _update_queue_depth() -> None:
    client = Redis.from_url(
        get_settings().redis_url.get_secret_value(),
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        depth = client.llen("celery")
        if isinstance(depth, int):
            CELERY_QUEUE_DEPTH.set(depth)
    except (OSError, RedisError, TimeoutError):
        CELERY_QUEUE_DEPTH.set(-1)
    finally:
        client.close()
