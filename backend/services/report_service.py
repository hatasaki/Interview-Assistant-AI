"""Background interview report generation.

Runs the pipeline: transcript curation -> report generation -> vectorization.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from services import agent_service, cosmos_service
from models.schemas import new_report_doc, new_interview_record_doc

logger = logging.getLogger(__name__)


def generate_report(interview_id: str, lang: str = "ja", notify_callback=None) -> None:
    """Generate an interview report in the background (sync).

    Flow:
    1. Curate transcript (remove noise + duplicate context)
    2. Save curated transcript + interview metadata to CosmosDB
    3. Generate report from curated transcript
    4. Vectorize curated transcript, interview details, and report
    """
    interview = cosmos_service.get_interview(interview_id)
    if not interview:
        logger.error("Interview %s not found", interview_id)
        return

    report_doc = new_report_doc(interview_id)
    cosmos_service.create_report(report_doc)

    try:
        transcripts = cosmos_service.list_transcripts(interview_id)
        agent_responses = cosmos_service.list_agent_responses(interview_id)
        chat_messages = cosmos_service.list_chat_messages(interview_id)

        # ── Step 1: Curate transcript ──
        logger.info("Curating transcript for interview %s with %d transcripts", interview_id, len(transcripts))
        curated_transcript = agent_service.curate_transcript(transcripts)
        logger.info("Transcript curation completed for interview %s", interview_id)

        # ── Step 2: Save curated transcript + interview metadata to CosmosDB ──
        record_doc = new_interview_record_doc(
            interview_id=interview_id,
            curated_transcript=curated_transcript,
            interview=interview,
            report_markdown="",
        )
        cosmos_service.create_interview_record(record_doc)
        logger.info("Curated transcript saved for interview %s", interview_id)

        # ── Step 3: Generate report using curated transcript ──
        logger.info("Generating report for interview %s", interview_id)
        markdown = agent_service.generate_report(
            interview, transcripts, agent_responses, chat_messages, lang,
            curated_transcript=curated_transcript,
        )

        report_doc["markdownContent"] = markdown
        report_doc["status"] = "completed"
        report_doc["completedAt"] = datetime.now(timezone.utc).isoformat()
        cosmos_service.update_report(report_doc)
        logger.info("Report generated for interview %s", interview_id)

        # ── Step 4: Save report to interview record ──
        record_doc["reportMarkdown"] = markdown
        record_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        cosmos_service.update_interview_record(record_doc)
        logger.info("Report saved to interview record for %s", interview_id)

        # ── Step 5: Vectorize interview record ──
        _vectorize_interview_record(record_doc, interview)

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.exception("Failed to generate report for interview %s", interview_id)
        report_doc["status"] = "failed"
        error_title = "# Report Generation Error" if lang == "en" else "# レポート生成エラー"
        report_doc["markdownContent"] = f"{error_title}\n\n```\n{error_detail}\n```"
        cosmos_service.update_report(report_doc)


def _vectorize_interview_record(record_doc: dict, interview: dict) -> None:
    """Vectorize curated transcript, interview details, and report, then update the record."""
    interview_id = record_doc["interviewId"]
    try:
        embedding_text = _build_embedding_text(record_doc, interview)

        logger.info("Generating embedding for interview %s", interview_id)
        embedding = agent_service.generate_embedding(embedding_text)

        record_doc["embedding"] = embedding
        record_doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
        cosmos_service.update_interview_record(record_doc)
        logger.info("Vectorization completed for interview %s", interview_id)

    except Exception:
        logger.exception("Failed to vectorize interview record %s (report is still saved)", interview_id)


def _build_embedding_text(record_doc: dict, interview: dict) -> str:
    """Build a combined text representation for embedding."""
    parts = [
        f"Interviewee: {record_doc.get('intervieweeName', '')} ({record_doc.get('intervieweeAffiliation', '')})",
        f"Date: {record_doc.get('interviewDate', '')}",
        f"Start: {record_doc.get('startTime', '')}",
        f"End: {record_doc.get('endTime', '')}",
        f"Goal: {record_doc.get('goal', '')}",
        f"Related Info: {record_doc.get('relatedInfo', '')}",
        "",
        "Curated Transcript:",
        record_doc.get("curatedTranscript", ""),
        "",
        "Report:",
        record_doc.get("reportMarkdown", ""),
    ]
    return "\n".join(parts)
