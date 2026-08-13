import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError


def issue_agent_certificate(csr_pem: str, agent_id: UUID) -> tuple[str, str, str, datetime, str]:
    settings = get_settings()
    ca_certificate = _load_certificate(settings.agent_ca_certificate_path)
    ca_key = _load_rsa_private_key(settings.agent_ca_key_path)
    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        if not csr.is_signature_valid:
            raise ValueError("invalid CSR signature")
        if not isinstance(csr.public_key(), rsa.RSAPublicKey):
            raise ValueError("only RSA agent keys are accepted")
    except (TypeError, ValueError, x509.ExtensionNotFound):
        raise ApplicationError(
            code="AIOPS_4004", message="Agent CSR 无效", status_code=422
        ) from None

    now = datetime.now(UTC)
    not_after = now + timedelta(hours=settings.agent_certificate_ttl_hours)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"aiops-x-agent-{agent_id}")])
        )
        .issuer_name(ca_certificate.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    certificate_der = certificate.public_bytes(serialization.Encoding.DER)
    return (
        certificate.public_bytes(serialization.Encoding.PEM).decode(),
        ca_certificate.public_bytes(serialization.Encoding.PEM).decode(),
        format(certificate.serial_number, "x"),
        not_after,
        hashlib.sha256(certificate_der).hexdigest(),
    )


def csr_fingerprint(csr_pem: str) -> str:
    try:
        csr = x509.load_pem_x509_csr(csr_pem.encode())
        if not csr.is_signature_valid:
            raise ValueError
    except ValueError:
        raise ApplicationError(
            code="AIOPS_4004", message="Agent CSR 无效", status_code=422
        ) from None
    return hashlib.sha256(csr.public_bytes(serialization.Encoding.DER)).hexdigest()


def normalize_certificate_serial(value: str) -> str:
    """Return the canonical hexadecimal form used by cryptography and PostgreSQL.

    Nginx exposes ``$ssl_client_serial`` from the ASN.1 INTEGER encoding and may
    retain its sign-padding zero.  ``cryptography`` exposes the same positive
    integer without that padding.  Normalize the trusted proxy header before a
    database lookup, while rejecting anything other than a bounded hex value.
    """
    candidate = value.strip()
    if not candidate or len(candidate) > 64:
        raise ValueError("invalid certificate serial")
    try:
        return format(int(candidate, 16), "x")
    except ValueError:
        raise ValueError("invalid certificate serial") from None


def verify_proxy_certificate(pem_certificate: str, expected_serial: str) -> str:
    settings = get_settings()
    ca_certificate = _load_certificate(settings.agent_ca_certificate_path)
    try:
        certificate = x509.load_pem_x509_certificate(pem_certificate.encode())
        if format(certificate.serial_number, "x") != normalize_certificate_serial(expected_serial):
            raise ValueError
        ca_public_key = ca_certificate.public_key()
        if not isinstance(ca_public_key, rsa.RSAPublicKey):
            raise ValueError
        signature_hash_algorithm = certificate.signature_hash_algorithm
        if signature_hash_algorithm is None:
            raise ValueError
        ca_public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash_algorithm,
        )
        now = datetime.now(UTC)
        if certificate.not_valid_before_utc > now or certificate.not_valid_after_utc <= now:
            raise ValueError
        usages = certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
        if ExtendedKeyUsageOID.CLIENT_AUTH not in usages:
            raise ValueError
    except (TypeError, ValueError, x509.ExtensionNotFound, x509.InvalidVersion):
        raise ApplicationError(
            code="AIOPS_4001", message="Agent 客户端证书无效", status_code=401
        ) from None
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def canonical_task_payload(task: dict[str, Any]) -> str:
    return json.dumps(task, separators=(",", ":"), sort_keys=True)


def sign_task(payload: str) -> str:
    import base64

    private_key = _load_rsa_private_key(get_settings().agent_task_signing_key_path)
    signature = private_key.sign(
        payload.encode(),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode()


def task_signing_certificate_pem() -> str:
    certificate = _load_certificate(get_settings().agent_task_signing_certificate_path)
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


def _load_certificate(path: str) -> x509.Certificate:
    try:
        return x509.load_pem_x509_certificate(Path(path).read_bytes())
    except (OSError, ValueError):
        raise ApplicationError(
            code="AIOPS_4099", message="Agent PKI 尚未配置", status_code=503
        ) from None


def _load_rsa_private_key(path: str) -> rsa.RSAPrivateKey:
    try:
        private_key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
        if not isinstance(private_key, rsa.RSAPrivateKey):
            raise ValueError
        return private_key
    except (OSError, TypeError, ValueError):
        raise ApplicationError(
            code="AIOPS_4099", message="Agent PKI 尚未配置", status_code=503
        ) from None
