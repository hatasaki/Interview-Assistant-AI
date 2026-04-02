import os


AZURE_COSMOS_DB_ENDPOINT: str = os.environ.get("AZURE_COSMOS_DB_ENDPOINT", "")
AZURE_AI_PROJECT_ENDPOINT: str = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_VOICELIVE_ENDPOINT: str = os.environ.get("AZURE_VOICELIVE_ENDPOINT", "")
AZURE_VOICELIVE_MODEL: str = os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-4o-mini")

COSMOS_DATABASE_NAME: str = "interview-assistant-db"
AGENT_NAME: str = "interview-assistant"
VOICELIVE_TOKEN_SCOPE: str = "https://cognitiveservices.azure.com/.default"
