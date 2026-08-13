import asyncio
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from aiops_x_api.core.config import get_settings
from aiops_x_api.core.errors import ApplicationError


def _client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )


async def put_report(*, object_name: str, content: bytes, content_type: str) -> str:
    settings = get_settings()

    def upload() -> str:
        client = _client()
        if not client.bucket_exists(settings.report_bucket):
            client.make_bucket(settings.report_bucket)
        client.put_object(
            settings.report_bucket,
            object_name,
            BytesIO(content),
            len(content),
            content_type=content_type,
        )
        return f"s3://{settings.report_bucket}/{object_name}"

    try:
        return await asyncio.to_thread(upload)
    except (S3Error, OSError, ValueError) as exc:
        raise ApplicationError(
            code="AIOPS_8601",
            message="报告对象存储暂时不可用",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc


async def get_report(object_ref: str, *, max_bytes: int = 20 * 1024 * 1024) -> bytes:
    settings = get_settings()
    prefix = f"s3://{settings.report_bucket}/"
    if not object_ref.startswith(prefix):
        raise ApplicationError(code="AIOPS_8604", message="报告对象引用无效", status_code=404)
    object_name = object_ref[len(prefix) :]

    def download() -> bytes:
        client = _client()
        response = client.get_object(settings.report_bucket, object_name)
        try:
            body = response.read(max_bytes + 1)
        finally:
            response.close()
            response.release_conn()
        if len(body) > max_bytes:
            raise ValueError("report_too_large")
        return body

    try:
        return await asyncio.to_thread(download)
    except (S3Error, OSError, ValueError) as exc:
        raise ApplicationError(
            code="AIOPS_8605",
            message="报告文件暂时无法读取",
            status_code=503,
            details={"reason": type(exc).__name__},
        ) from exc
