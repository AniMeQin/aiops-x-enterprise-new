import os
import subprocess
import sys
from pathlib import Path


def test_worker_registers_event_outbox_foreign_key_dependencies() -> None:
    project_root = Path(__file__).resolve().parents[1]
    python_paths = [
        project_root / "apps/api/src",
        project_root / "apps/worker/src",
    ]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in python_paths)
    environment["AIOPS_OTEL_EXPORTER_OTLP_ENDPOINT"] = ""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from aiops_x_api.core.database import Base; "
                "from aiops_x_worker.tasks import EventOutbox; "
                "assert EventOutbox.__tablename__ == 'event_outbox'; "
                "assert {'tenants', 'projects', 'event_outbox'} <= set(Base.metadata.tables); "
                "list(Base.metadata.sorted_tables)"
            ),
        ],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
