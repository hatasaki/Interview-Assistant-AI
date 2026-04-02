from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from models.schemas import (
    new_agent_response_doc,
    new_chat_message_doc,
    new_transcript_doc,
)
from services import agent_service, cosmos_service

logger = logging.getLogger(__name__)

router = APIRouter()

_connections: dict[str, list[WebSocket]] = {}
_seq_counters: dict[str, int] = {}
_interview_cache: dict[str, dict] = {}
_initial_done: set[str] = set()
_lang_cache: dict[str, str] = {}

AGENT_TIMEOUT = 60  # seconds


def _interview_context(interview: dict) -> str:
    """Build interview context string for agent prompts."""
    return (
        f"対象者: {interview.get('intervieweeName', '')} "
        f"({interview.get('intervieweeAffiliation', '')})\n"
        f"関連情報: {interview.get('relatedInfo', '')}\n"
        f"インタビュー時間: {interview.get('durationMinutes', '')}分\n"
        f"ゴール: {interview.get('goal', '')}"
    )


async def notify_report_ready(interview_id: str, report_id: str) -> None:
    msg = json.dumps({"type": "report_ready", "reportId": report_id})
    for ws in _connections.get(interview_id, []):
        try:
            await ws.send_text(msg)
        except Exception:
            pass


@router.websocket("/ws/interview/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str, lang: str = Query(default="ja")):
    await websocket.accept()

    if interview_id not in _connections:
        _connections[interview_id] = []
    _connections[interview_id].append(websocket)

    # Store language preference
    _lang_cache[interview_id] = lang

    # Initialize on first connection
    if interview_id not in _initial_done:
        _initial_done.add(interview_id)

        interview = cosmos_service.get_interview(interview_id)
        _interview_cache[interview_id] = interview or {}

        if interview:
            conv_id = agent_service.create_conversation()
            context_msg = (
                f"インタビュー開始。\n"
                f"{_interview_context(interview)}\n\n"
                f"最初にInterviewerが声掛けするための内容案と最初の質問候補を提示してください。"
            )
            try:
                suggestion = await asyncio.to_thread(
                    agent_service.send_message, conv_id, context_msg, lang
                )
                await _send_full(websocket, suggestion)
            except Exception as e:
                logger.error("Initial agent call failed: %s", e)

    if interview_id not in _seq_counters:
        _seq_counters[interview_id] = 0

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "transcript":
                await _handle_transcript(interview_id, msg)
            elif msg_type == "supplementary_info":
                asyncio.create_task(_handle_supplementary(interview_id, msg))
            elif msg_type == "generate_questions":
                asyncio.create_task(_handle_generate_questions(interview_id))
            elif msg_type == "chat_message":
                asyncio.create_task(_handle_chat_message(interview_id, msg))

    except WebSocketDisconnect:
        _connections[interview_id].remove(websocket)
        if not _connections[interview_id]:
            del _connections[interview_id]


async def _handle_transcript(interview_id: str, msg: dict) -> None:
    """Save transcript to DB only. Supplementary info is triggered separately."""
    text = msg.get("text", "")
    if not text or len(text.strip()) < 3:
        return

    _seq_counters[interview_id] += 1
    seq = _seq_counters[interview_id]

    doc = new_transcript_doc(interview_id, text, seq)
    await asyncio.to_thread(cosmos_service.create_transcript, doc)


async def _handle_supplementary(interview_id: str, msg: dict) -> None:
    """Role 1: Generate supplementary info. Fresh conversation each time."""
    text = msg.get("text", "")
    if not text or len(text.strip()) < 10:
        return

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    conv_id = agent_service.create_conversation()

    agent_input = (
        f"[文字起こし・補足情報リクエスト]\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"## 会話内容\n{text}\n\n"
        f"上記の会話内容に含まれる専門用語や技術概念を検出し、"
        f"素人のinterviewerが理解できるよう補足情報を提供してください。"
        f"suggested_questionsは空配列にしてください。"
    )
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(agent_service.send_message, conv_id, agent_input, lang),
            timeout=AGENT_TIMEOUT
        )
        for ws in _connections.get(interview_id, []):
            refs = suggestion.get("references", [])
            await ws.send_text(json.dumps({
                "type": "agent_suggestion",
                "relatedInfo": suggestion.get("relatedInfo", ""),
                "suggestedQuestions": [],
                "references": refs,
            }, ensure_ascii=False))
            if refs:
                await ws.send_text(json.dumps({
                    "type": "agent_references", "references": refs,
                }, ensure_ascii=False))
    except asyncio.TimeoutError:
        logger.warning("Supplementary agent call timed out for %s", interview_id)
    except Exception as e:
        logger.error("Agent supplementary call failed: %s", e)


async def _handle_generate_questions(interview_id: str) -> None:
    """Role 2: Generate questions. Uses a fresh conversation each time."""
    transcripts = await asyncio.to_thread(
        cosmos_service.list_transcripts, interview_id
    )
    transcript_text = "\n".join(t.get("text", "") for t in transcripts)
    if not transcript_text:
        return

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    conv_id = agent_service.create_conversation()

    agent_input = (
        f"[質問生成リクエスト]\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"## 直近の文字起こし履歴\n{transcript_text[-5000:]}\n\n"
        f"上記のインタビュー情報とゴール、文字起こし履歴に基づいて、"
        f"次にInterviewerが聞くべき効果的な質問案を最大3個提示してください。"
        f"related_infoは空文字列にしてください。"
    )
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(agent_service.send_message, conv_id, agent_input, lang),
            timeout=AGENT_TIMEOUT
        )
        for ws in _connections.get(interview_id, []):
            await ws.send_text(json.dumps({
                "type": "agent_suggestion",
                "relatedInfo": "",
                "suggestedQuestions": suggestion.get("suggestedQuestions", []),
                "references": [],
            }, ensure_ascii=False))
    except asyncio.TimeoutError:
        logger.warning("Question generation timed out for %s", interview_id)
    except Exception as e:
        logger.error("Agent question generation failed: %s", e)


async def _handle_chat_message(interview_id: str, msg: dict) -> None:
    """Role 3: Chat Q&A. Uses a fresh conversation, minimal DB writes."""
    content = msg.get("content", "")
    if not content:
        return

    transcripts = await asyncio.to_thread(
        cosmos_service.list_transcripts, interview_id
    )
    transcript_text = "\n".join(t.get("text", "") for t in transcripts)

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    conv_id = agent_service.create_conversation()

    agent_input = (
        f"[Interviewerからのチャット質問]\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"## 直近の文字起こし履歴\n{transcript_text[-5000:]}\n\n"
        f"## Interviewerの質問\n{content}\n\n"
        f"上記の文脈を踏まえてInterviewerの質問に回答し、"
        f"関連する参照情報があれば提供してください。"
        f"質問案は不要なのでsuggested_questionsは空配列にしてください。"
    )
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(agent_service.send_message, conv_id, agent_input, lang),
            timeout=AGENT_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("Chat agent call timed out for %s", interview_id)
        return
    except Exception as e:
        logger.error("Agent chat call failed: %s", e)
        return

    # Add "chat" card title, strip questions, and send
    suggestion["cardTitle"] = "Chat" if lang == "en" else "チャット"
    suggestion["suggestedQuestions"] = []  # Chat should not include question suggestions
    for ws in _connections.get(interview_id, []):
        await _send_full(ws, suggestion)


async def _send_full(ws: WebSocket, suggestion: dict) -> None:
    try:
        refs = suggestion.get("references", [])
        msg = {
            "type": "agent_suggestion",
            "relatedInfo": suggestion.get("relatedInfo", ""),
            "suggestedQuestions": suggestion.get("suggestedQuestions", []),
            "references": refs,
        }
        if "cardTitle" in suggestion:
            msg["cardTitle"] = suggestion["cardTitle"]
        await ws.send_text(json.dumps(msg, ensure_ascii=False))
        if refs:
            await ws.send_text(json.dumps({
                "type": "agent_references", "references": refs,
            }, ensure_ascii=False))
    except Exception:
        pass
