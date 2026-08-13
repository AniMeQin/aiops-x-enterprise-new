from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiops_x_api.core.config import get_settings
from aiops_x_api.core.database import Base, get_session
from aiops_x_api.main import create_app
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class MilestoneContext:
    client: TestClient
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
async def milestone_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[MilestoneContext]:
    _configure_test_agent_pki(tmp_path, monkeypatch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield MilestoneContext(client=client, session_factory=factory)
    app.dependency_overrides.clear()
    await engine.dispose()
    get_settings.cache_clear()


def _configure_test_agent_pki(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Milestone Agent CA")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    task_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    task_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Milestone Task Signing")])
    task_certificate = (
        x509.CertificateBuilder()
        .subject_name(task_name)
        .issuer_name(task_name)
        .public_key(task_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]), critical=False)
        .sign(task_key, hashes.SHA256())
    )

    files = {
        "AIOPS_AGENT_CA_KEY_PATH": (tmp_path / "ca-key.pem", _private_pem(ca_key)),
        "AIOPS_AGENT_CA_CERTIFICATE_PATH": (
            tmp_path / "ca-cert.pem",
            ca_certificate.public_bytes(serialization.Encoding.PEM),
        ),
        "AIOPS_AGENT_TASK_SIGNING_KEY_PATH": (
            tmp_path / "task-key.pem",
            _private_pem(task_key),
        ),
        "AIOPS_AGENT_TASK_SIGNING_CERTIFICATE_PATH": (
            tmp_path / "task-cert.pem",
            task_certificate.public_bytes(serialization.Encoding.PEM),
        ),
    }
    for environment_name, (path, content) in files.items():
        path.write_bytes(content)
        monkeypatch.setenv(environment_name, str(path))
    get_settings.cache_clear()


def _private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
