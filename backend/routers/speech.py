"""Endpoint for acquiring Azure Speech Service tokens."""

from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter
from azure.identity import DefaultAzureCredential

from config import AZURE_SPEECH_ENDPOINT, SPEECH_TOKEN_SCOPE

router = APIRouter(prefix="/api/speech", tags=["speech"])

_credential = DefaultAzureCredential()


def _extract_region(endpoint: str) -> str:
    """Extract region from AI Services endpoint URL.

    Handles formats like:
      https://<resource>.cognitiveservices.azure.com/
      https://<resource>.services.ai.azure.com/
      https://<region>.api.cognitive.microsoft.com/
    For custom domain endpoints, the region is obtained from the
    AZURE_SPEECH_REGION env var or defaults to the subdomain.
    """
    import os
    region = os.environ.get("AZURE_SPEECH_REGION", "")
    if region:
        return region

    parsed = urlparse(endpoint)
    host = parsed.hostname or ""
    # e.g. eastus.api.cognitive.microsoft.com
    if ".api.cognitive.microsoft.com" in host:
        return host.split(".")[0]
    # For custom domain endpoints, return the full host
    # Speech SDK uses custom endpoint when region alone is insufficient
    return host


@router.get("/token")
async def get_speech_token():
    """Return an Entra ID token, region, and endpoint for the Speech SDK."""
    token = _credential.get_token(SPEECH_TOKEN_SCOPE)
    region = _extract_region(AZURE_SPEECH_ENDPOINT)
    return {
        "token": token.token,
        "region": region,
        "endpoint": AZURE_SPEECH_ENDPOINT,
    }
