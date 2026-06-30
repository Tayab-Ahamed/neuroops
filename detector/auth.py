"""
auth.py — API key authentication dependency for FastAPI.

Set the NEUROOPS_API_KEY environment variable to enable auth.
If unset (empty string), authentication is disabled — safe for local dev.

Usage:
    from auth import verify_api_key
    from fastapi import Depends

    @app.post("/investigate", dependencies=[Depends(verify_api_key)])
    async def investigate(...):
        ...
"""
import os

import structlog
from fastapi import Header, HTTPException, status

logger = structlog.get_logger()

_API_KEY = os.getenv("NEUROOPS_API_KEY", "")


def verify_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """
    FastAPI dependency — validates X-API-Key header when NEUROOPS_API_KEY is configured.
    Passes silently when no API key is configured (dev/open mode).
    """
    if not _API_KEY:
        return  # Auth disabled — dev mode
    if not x_api_key or x_api_key != _API_KEY:
        logger.warning("Rejected request: invalid or missing X-API-Key header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": "Invalid or missing X-API-Key header"},
            headers={"WWW-Authenticate": "ApiKey"},
        )
