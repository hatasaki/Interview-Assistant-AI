"""Application-wide environment variables and constants."""

import os


AZURE_COSMOS_DB_ENDPOINT: str = os.environ.get("AZURE_COSMOS_DB_ENDPOINT", "")
AZURE_AI_PROJECT_ENDPOINT: str = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_SPEECH_ENDPOINT: str = os.environ.get("AZURE_SPEECH_ENDPOINT", "")

COSMOS_DATABASE_NAME: str = "interview-assistant-db"
AGENT_NAME: str = "interview-assistant"
AGENT_MODEL: str = os.environ.get("AZURE_AGENT_MODEL", "gpt-4o")
EMBEDDING_MODEL: str = os.environ.get("AZURE_EMBEDDING_MODEL", "text-embedding-3-small")
SPEECH_TOKEN_SCOPE: str = "https://cognitiveservices.azure.com/.default"
