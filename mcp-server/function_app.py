"""MCP Server for Interview Assistant AI - Vector Search Tools.

Provides 3 MCP tools via Azure Functions Streamable MCP Trigger:
1. search_interviews - Vector search by query to find related interviews
2. get_interview_report - Get report and basic info by interview ID
3. get_interview_details - Get full details including curated transcript by interview ID
"""

import json
import logging
import os

import azure.functions as func
from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

# Configure Azure Monitor OpenTelemetry for custom traces/logs/metrics.
# The Functions host emits its own request telemetry when
# APPLICATIONINSIGHTS_CONNECTION_STRING is set; this call adds OTel-based
# tracing for Cosmos DB / OpenAI / requests inside user code.
if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor()
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed to configure Azure Monitor OpenTelemetry"
        )

app = func.FunctionApp()

logger = logging.getLogger(__name__)

# ── Configuration ──
COSMOS_ENDPOINT = os.environ.get("AZURE_COSMOS_DB_ENDPOINT", "")
AI_PROJECT_ENDPOINT = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
EMBEDDING_MODEL = os.environ.get("AZURE_EMBEDDING_MODEL", "text-embedding-3-small")
DATABASE_NAME = "interview-assistant-db"
CONTAINER_NAME = "interview_records"

# ── Shared clients (lazy init) ──
_cosmos_client = None
_openai_client = None
_credential = None


def _get_credential():
    """Return the shared DefaultAzureCredential instance."""
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _get_cosmos_container():
    """Return the interview_records container client."""
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosClient(COSMOS_ENDPOINT, credential=_get_credential())
    db = _cosmos_client.get_database_client(DATABASE_NAME)
    return db.get_container_client(CONTAINER_NAME)


def _get_openai_client():
    """Return the shared AzureOpenAI client for embedding generation."""
    global _openai_client
    if _openai_client is None:
        # Extract the base endpoint from the project endpoint
        # Project endpoint: https://<name>.services.ai.azure.com/api/projects/<project>
        # Base endpoint: https://<name>.services.ai.azure.com
        base_endpoint = AI_PROJECT_ENDPOINT.split("/api/projects/")[0] if "/api/projects/" in AI_PROJECT_ENDPOINT else AI_PROJECT_ENDPOINT
        credential = _get_credential()
        _openai_client = AzureOpenAI(
            azure_endpoint=base_endpoint,
            azure_ad_token_provider=lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token,
            api_version="2024-10-21",
        )
    return _openai_client


def _generate_query_embedding(query: str) -> list[float]:
    """Generate embedding vector for a search query."""
    client = _get_openai_client()
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    return response.data[0].embedding


# ── Tool properties (JSON) ──
_SEARCH_PROPERTIES = json.dumps([
    {
        "propertyName": "query",
        "propertyType": "string",
        "description": "Search query text to find related interviews",
        "isRequired": True,
    },
    {
        "propertyName": "top_n",
        "propertyType": "number",
        "description": "Number of results to return (default: 5)",
    },
])

_ID_PROPERTY = json.dumps([
    {
        "propertyName": "id",
        "propertyType": "string",
        "description": "Interview ID (partition key from search results)",
        "isRequired": True,
    },
])


# ── Tool 1: Search Interviews by Vector Similarity ──
@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="search_interviews",
    description="Search interviews by semantic similarity. Returns a list of matching interviews with basic info.",
    tool_properties=_SEARCH_PROPERTIES,
)
def search_interviews(context) -> str:
    """Vector search on interview records and return matching interviews."""
    try:
        content = json.loads(context)
        arguments = content.get("arguments", {})
        query = arguments.get("query", "")
        top_n = int(arguments.get("top_n", 5))

        if not query:
            return json.dumps({"error": "query is required"})

        # Generate embedding for the query
        query_embedding = _generate_query_embedding(query)

        # Perform vector search using Cosmos DB
        container = _get_cosmos_container()
        results = container.query_items(
            query=(
                "SELECT TOP @top_n "
                "c.id, c.intervieweeName, c.intervieweeAffiliation, "
                "c.interviewDate, c.startTime, "
                "VectorDistance(c.embedding, @embedding) AS similarityScore "
                "FROM c "
                "WHERE c.type = 'interview_record' "
                "ORDER BY VectorDistance(c.embedding, @embedding)"
            ),
            parameters=[
                {"name": "@top_n", "value": top_n},
                {"name": "@embedding", "value": query_embedding},
            ],
            enable_cross_partition_query=True,
        )

        interviews = []
        for item in results:
            interviews.append({
                "id": item["id"],
                "intervieweeName": item["intervieweeName"],
                "intervieweeAffiliation": item["intervieweeAffiliation"],
                "interviewDate": item["interviewDate"],
                "startTime": item["startTime"],
                "similarityScore": item.get("similarityScore"),
            })

        return json.dumps({"results": interviews, "count": len(interviews)}, ensure_ascii=False)

    except Exception as e:
        logger.exception("Error in search_interviews")
        return json.dumps({"error": str(e)})


# ── Tool 2: Get Interview Report by ID ──
@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="get_interview_report",
    description="Get the interview report and basic info by interview ID.",
    tool_properties=_ID_PROPERTY,
)
def get_interview_report(context) -> str:
    """Get report and basic metadata for a specific interview."""
    try:
        content = json.loads(context)
        arguments = content.get("arguments", {})
        interview_id = arguments.get("id", "")

        if not interview_id:
            return json.dumps({"error": "id is required"})

        container = _get_cosmos_container()
        try:
            item = container.read_item(item=interview_id, partition_key=interview_id)
        except Exception:
            return json.dumps({"error": f"Interview record not found: {interview_id}"})

        result = {
            "id": item["id"],
            "intervieweeName": item.get("intervieweeName", ""),
            "intervieweeAffiliation": item.get("intervieweeAffiliation", ""),
            "interviewDate": item.get("interviewDate", ""),
            "startTime": item.get("startTime", ""),
            "endTime": item.get("endTime", ""),
            "reportMarkdown": item.get("reportMarkdown", ""),
        }

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.exception("Error in get_interview_report")
        return json.dumps({"error": str(e)})


# ── Tool 3: Get Full Interview Details by ID ──
@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="get_interview_details",
    description="Get full interview details including curated transcript, interview metadata, and report by interview ID.",
    tool_properties=_ID_PROPERTY,
)
def get_interview_details(context) -> str:
    """Get full details for a specific interview."""
    try:
        content = json.loads(context)
        arguments = content.get("arguments", {})
        interview_id = arguments.get("id", "")

        if not interview_id:
            return json.dumps({"error": "id is required"})

        container = _get_cosmos_container()
        try:
            item = container.read_item(item=interview_id, partition_key=interview_id)
        except Exception:
            return json.dumps({"error": f"Interview record not found: {interview_id}"})

        result = {
            "id": item["id"],
            "intervieweeName": item.get("intervieweeName", ""),
            "intervieweeAffiliation": item.get("intervieweeAffiliation", ""),
            "relatedInfo": item.get("relatedInfo", ""),
            "goal": item.get("goal", ""),
            "interviewDate": item.get("interviewDate", ""),
            "startTime": item.get("startTime", ""),
            "endTime": item.get("endTime", ""),
            "curatedTranscript": item.get("curatedTranscript", ""),
            "reportMarkdown": item.get("reportMarkdown", ""),
        }

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.exception("Error in get_interview_details")
        return json.dumps({"error": str(e)})
