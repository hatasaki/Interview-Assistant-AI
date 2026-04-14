from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Request / Response Models ──


class InterviewCreate(BaseModel):
    intervieweeName: str
    intervieweeAffiliation: str
    relatedInfo: str = ""
    durationMinutes: int
    goal: str


class InterviewOut(BaseModel):
    id: str
    interviewId: str
    type: str = "interview_metadata"
    intervieweeName: str
    intervieweeAffiliation: str
    relatedInfo: str
    durationMinutes: int
    goal: str
    status: str
    startedAt: Optional[str] = None
    endedAt: Optional[str] = None
    createdAt: str
    updatedAt: str


class ReportStatus(BaseModel):
    status: str
    reportId: Optional[str] = None


class ReportOut(BaseModel):
    id: str
    interviewId: str
    markdownContent: str
    status: str
    createdAt: str
    completedAt: Optional[str] = None


class SuggestedQuestion(BaseModel):
    type: str = ""
    question: str
    rationale: str


class Reference(BaseModel):
    title: str
    url: str


class AgentSuggestion(BaseModel):
    relatedInfo: str = ""
    suggestedQuestions: list[SuggestedQuestion] = []
    references: list[Reference] = []


# ── Cosmos DB Document helpers ──


def new_interview_doc(data: InterviewCreate) -> dict:
    doc_id = _new_id()
    now = _utcnow()
    return {
        "id": doc_id,
        "interviewId": doc_id,
        "type": "interview_metadata",
        "intervieweeName": data.intervieweeName,
        "intervieweeAffiliation": data.intervieweeAffiliation,
        "relatedInfo": data.relatedInfo,
        "durationMinutes": data.durationMinutes,
        "goal": data.goal,
        "status": "not_started",
        "startedAt": None,
        "endedAt": None,
        "createdAt": now,
        "updatedAt": now,
    }


def new_transcript_doc(interview_id: str, text: str, seq: int) -> dict:
    return {
        "id": _new_id(),
        "interviewId": interview_id,
        "type": "transcript_entry",
        "text": text,
        "timestamp": _utcnow(),
        "sequenceNumber": seq,
    }


def new_chat_message_doc(interview_id: str, role: str, content: str) -> dict:
    return {
        "id": _new_id(),
        "interviewId": interview_id,
        "type": "chat_message",
        "role": role,
        "content": content,
        "timestamp": _utcnow(),
    }


def new_agent_response_doc(
    interview_id: str,
    related_info: str,
    suggested_questions: list[dict],
    references: list[dict],
    trigger_transcript_id: str | None = None,
) -> dict:
    return {
        "id": _new_id(),
        "interviewId": interview_id,
        "type": "agent_response",
        "relatedInfo": related_info,
        "suggestedQuestions": suggested_questions,
        "references": references,
        "timestamp": _utcnow(),
        "triggerTranscriptId": trigger_transcript_id,
    }


def new_report_doc(interview_id: str) -> dict:
    return {
        "id": _new_id(),
        "interviewId": interview_id,
        "type": "report",
        "markdownContent": "",
        "status": "generating",
        "createdAt": _utcnow(),
        "completedAt": None,
    }


def new_interview_record_doc(
    interview_id: str,
    curated_transcript: str,
    interview: dict,
    report_markdown: str,
) -> dict:
    return {
        "id": interview_id,
        "interviewId": interview_id,
        "type": "interview_record",
        "intervieweeName": interview.get("intervieweeName", ""),
        "intervieweeAffiliation": interview.get("intervieweeAffiliation", ""),
        "relatedInfo": interview.get("relatedInfo", ""),
        "goal": interview.get("goal", ""),
        "interviewDate": interview.get("createdAt", ""),
        "startTime": interview.get("startedAt", ""),
        "endTime": interview.get("endedAt", ""),
        "curatedTranscript": curated_transcript,
        "reportMarkdown": report_markdown,
        "embedding": [],
        "createdAt": _utcnow(),
        "updatedAt": _utcnow(),
    }
