"""Endpoint for acquiring Voice Live API tokens."""

from __future__ import annotations

from fastapi import APIRouter
from azure.identity import DefaultAzureCredential

from config import AZURE_VOICELIVE_ENDPOINT, AZURE_VOICELIVE_MODEL, VOICELIVE_TOKEN_SCOPE

router = APIRouter(prefix="/api/voicelive", tags=["voicelive"])

_credential = DefaultAzureCredential()


@router.get("/token")
async def get_voicelive_token():
    """Return an Entra ID token, endpoint, and model for the Voice Live API."""
    token = _credential.get_token(VOICELIVE_TOKEN_SCOPE)
    return {
        "token": token.token,
        "endpoint": AZURE_VOICELIVE_ENDPOINT,
        "model": AZURE_VOICELIVE_MODEL,
        "expiresOn": token.expires_on,
    }
