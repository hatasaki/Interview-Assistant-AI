"""Application-wide environment variables and constants."""

import os


AZURE_COSMOS_DB_ENDPOINT: str = os.environ.get("AZURE_COSMOS_DB_ENDPOINT", "")
AZURE_AI_PROJECT_ENDPOINT: str = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
AZURE_SPEECH_ENDPOINT: str = os.environ.get("AZURE_SPEECH_ENDPOINT", "")

COSMOS_DATABASE_NAME: str = "interview-assistant-db"

# ── Foundry Agents (role-specialized) ──
# Each role has its own agent so SYSTEM_PROMPTs stay focused and do not
# interfere with each other (related-info detection rules must not bleed
# into chat Q&A or question generation, etc.).
RELATED_INFO_AGENT_NAME: str = "interview-related-info"
QUESTIONS_AGENT_NAME: str = "interview-questions"
CHAT_AGENT_NAME: str = "interview-chat"

AGENT_MODEL: str = os.environ.get("AZURE_AGENT_MODEL", "gpt-4o")
EMBEDDING_MODEL: str = os.environ.get("AZURE_EMBEDDING_MODEL", "text-embedding-3-small")
SPEECH_TOKEN_SCOPE: str = "https://cognitiveservices.azure.com/.default"

# ── MCP servers (shared across all role agents) ──
# Single source of truth: editing this list updates every agent on the
# next ensure_agent() call. Add / remove / change URLs here only.
MCP_SERVERS: list[dict] = [
    {
        "label": "microsoft_learn",
        "url": "https://learn.microsoft.com/api/mcp",
    },
]
