from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone

from services import agent_service, cosmos_service
from models.schemas import new_report_doc

logger = logging.getLogger(__name__)


def generate_report(interview_id: str, lang: str = "ja", notify_callback=None) -> None:
    """Generate an interview report in the background (sync)."""
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

        logger.info("Generating report for interview %s with %d transcripts", interview_id, len(transcripts))

        markdown = agent_service.generate_report(
            interview, transcripts, agent_responses, chat_messages, lang
        )

        report_doc["markdownContent"] = markdown
        report_doc["status"] = "completed"
        report_doc["completedAt"] = datetime.now(timezone.utc).isoformat()
        cosmos_service.update_report(report_doc)

        logger.info("Report generated for interview %s", interview_id)

    except Exception as e:
        error_detail = traceback.format_exc()
        logger.exception("Failed to generate report for interview %s", interview_id)
        report_doc["status"] = "failed"
        error_title = "# Report Generation Error" if lang == "en" else "# レポート生成エラー"
        report_doc["markdownContent"] = f"{error_title}\n\n```\n{error_detail}\n```"
        cosmos_service.update_report(report_doc)
