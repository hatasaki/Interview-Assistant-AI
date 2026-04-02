from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from models.schemas import (
    InterviewCreate,
    InterviewOut,
    ReportOut,
    ReportStatus,
    new_interview_doc,
)
from services import cosmos_service, report_service

router = APIRouter(prefix="/api/interviews", tags=["interviews"])


@router.post("", response_model=InterviewOut, status_code=201)
async def create_interview(data: InterviewCreate):
    doc = new_interview_doc(data)
    result = cosmos_service.create_interview(doc)
    return result


@router.get("/{interview_id}", response_model=InterviewOut)
async def get_interview(interview_id: str):
    doc = cosmos_service.get_interview(interview_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Interview not found")
    return doc


@router.post("/{interview_id}/start")
async def start_interview(interview_id: str):
    doc = cosmos_service.get_interview(interview_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Interview not found")
    doc["status"] = "in_progress"
    doc["startedAt"] = datetime.now(timezone.utc).isoformat()
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    cosmos_service.update_interview(doc)
    return {"status": "started"}


@router.post("/{interview_id}/stop")
async def stop_interview(interview_id: str, background_tasks: BackgroundTasks, lang: str = Query(default="ja")):
    doc = cosmos_service.get_interview(interview_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Interview not found")
    doc["status"] = "completed"
    doc["endedAt"] = datetime.now(timezone.utc).isoformat()
    doc["updatedAt"] = datetime.now(timezone.utc).isoformat()
    cosmos_service.update_interview(doc)

    background_tasks.add_task(
        report_service.generate_report, interview_id, lang
    )
    return {"status": "stopped", "reportGenerating": True}


@router.get("/{interview_id}/report", response_model=ReportOut)
async def get_report(interview_id: str):
    report = cosmos_service.get_report(interview_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.get("/{interview_id}/report/status", response_model=ReportStatus)
async def get_report_status(interview_id: str):
    report = cosmos_service.get_report(interview_id)
    if not report:
        return ReportStatus(status="not_started")
    return ReportStatus(status=report["status"], reportId=report["id"])
