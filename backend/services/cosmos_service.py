"""Data access layer providing CRUD operations for each Cosmos DB container."""

from __future__ import annotations

from azure.cosmos import CosmosClient, PartitionKey
from azure.identity import DefaultAzureCredential

from config import AZURE_COSMOS_DB_ENDPOINT, COSMOS_DATABASE_NAME


# Singleton Cosmos DB client
_client: CosmosClient | None = None


def _get_client() -> CosmosClient:
    """Return the shared CosmosClient, creating it on first call."""
    global _client
    if _client is None:
        credential = DefaultAzureCredential()
        _client = CosmosClient(AZURE_COSMOS_DB_ENDPOINT, credential=credential)
    return _client


def _get_container(container_name: str):
    """Return a container client for the given container name."""
    db = _get_client().get_database_client(COSMOS_DATABASE_NAME)
    return db.get_container_client(container_name)


# ── Interviews ──


def create_interview(doc: dict) -> dict:
    container = _get_container("interviews")
    return container.create_item(body=doc)


def get_interview(interview_id: str) -> dict | None:
    container = _get_container("interviews")
    try:
        return container.read_item(item=interview_id, partition_key=interview_id)
    except Exception:
        return None


def update_interview(doc: dict) -> dict:
    container = _get_container("interviews")
    return container.upsert_item(body=doc)


# ── Transcripts ──


def create_transcript(doc: dict) -> dict:
    container = _get_container("transcripts")
    return container.create_item(body=doc)


def list_transcripts(interview_id: str) -> list[dict]:
    container = _get_container("transcripts")
    items = container.query_items(
        query="SELECT * FROM c WHERE c.interviewId = @iid ORDER BY c.sequenceNumber",
        parameters=[{"name": "@iid", "value": interview_id}],
        partition_key=interview_id,
    )
    return list(items)


# ── Agent Responses ──


def create_agent_response(doc: dict) -> dict:
    container = _get_container("agent_responses")
    return container.create_item(body=doc)


def list_agent_responses(interview_id: str) -> list[dict]:
    container = _get_container("agent_responses")
    items = container.query_items(
        query="SELECT * FROM c WHERE c.interviewId = @iid ORDER BY c.timestamp",
        parameters=[{"name": "@iid", "value": interview_id}],
        partition_key=interview_id,
    )
    return list(items)


# ── Chat Messages ──


def create_chat_message(doc: dict) -> dict:
    container = _get_container("chat_messages")
    return container.create_item(body=doc)


def list_chat_messages(interview_id: str) -> list[dict]:
    container = _get_container("chat_messages")
    items = container.query_items(
        query="SELECT * FROM c WHERE c.interviewId = @iid ORDER BY c.timestamp",
        parameters=[{"name": "@iid", "value": interview_id}],
        partition_key=interview_id,
    )
    return list(items)


# ── Reports ──


def create_report(doc: dict) -> dict:
    container = _get_container("reports")
    return container.create_item(body=doc)


def get_report(interview_id: str) -> dict | None:
    container = _get_container("reports")
    items = container.query_items(
        query="SELECT * FROM c WHERE c.interviewId = @iid ORDER BY c.createdAt DESC",
        parameters=[{"name": "@iid", "value": interview_id}],
        partition_key=interview_id,
    )
    result = list(items)
    return result[0] if result else None


def update_report(doc: dict) -> dict:
    container = _get_container("reports")
    return container.upsert_item(body=doc)


# ── Interview Records (with vector embeddings) ──


def create_interview_record(doc: dict) -> dict:
    container = _get_container("interview_records")
    return container.create_item(body=doc)


def update_interview_record(doc: dict) -> dict:
    container = _get_container("interview_records")
    return container.upsert_item(body=doc)


def get_interview_record(interview_id: str) -> dict | None:
    container = _get_container("interview_records")
    try:
        return container.read_item(item=interview_id, partition_key=interview_id)
    except Exception:
        return None
