from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from aiops_x_api.modules.identity.security import Principal, require_permission
from aiops_x_api.modules.secret_provider.service import get_secret_provider

router = APIRouter(prefix="/secret-provider", tags=["security"])


class SecretProviderStatusResponse(BaseModel):
    provider: str
    available: bool
    message: str


@router.get("/status", response_model=SecretProviderStatusResponse)
async def secret_provider_status(
    _: Annotated[Principal, Depends(require_permission("secret-provider:read"))],
) -> SecretProviderStatusResponse:
    status = await get_secret_provider().health()
    return SecretProviderStatusResponse(
        provider=status.provider, available=status.available, message=status.message
    )
