"""WebSocket endpoint for real-time communication during interviews.

Handles transcript saving, supplementary info, question generation, and chat.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from config import (
    CHAT_AGENT_NAME,
    QUESTIONS_AGENT_NAME,
    RELATED_INFO_AGENT_NAME,
)
from models.schemas import (
    new_agent_response_doc,
    new_chat_message_doc,
    new_transcript_doc,
)
from services import agent_service, cosmos_service

logger = logging.getLogger(__name__)

router = APIRouter()

# Per-interview WebSocket state
_connections: dict[str, list[WebSocket]] = {}   # active WS connections per interview
_seq_counters: dict[str, int] = {}              # transcript sequence numbers
_interview_cache: dict[str, dict] = {}          # cached interview metadata
_initial_done: set[str] = set()                 # interviews that completed initial agent call
_lang_cache: dict[str, str] = {}                # language preference per interview
_supplementary_chunks: dict[str, deque[str]] = {}  # rolling window of recent supplementary chunks
_used_keywords: dict[str, list[str]] = {}       # keywords already explained, per interview

AGENT_TIMEOUT = 60  # seconds
SUPPLEMENTARY_CHUNK_WINDOW = 5  # number of recent transcript chunks fed to the agent
QUESTIONS_HISTORY_CHARS = 30000  # transcript tail length used as full history for question generation
QUESTIONS_RECENT_CHARS = 2000    # transcript tail snippet used to anchor the current topic
CHAT_HISTORY_CHARS = 20000       # transcript tail length used as history for chat Q&A


def _interview_context(interview: dict) -> str:
    """Build interview context string for agent prompts."""
    return (
        f"対象者: {interview.get('intervieweeName', '')} "
        f"({interview.get('intervieweeAffiliation', '')})\n"
        f"関連情報: {interview.get('relatedInfo', '')}\n"
        f"インタビュー時間: {interview.get('durationMinutes', '')}分\n"
        f"ゴール: {interview.get('goal', '')}"
    )


def _format_transcript_line(t: dict) -> str:
    """Format a transcript entry for agent prompts, prefixing the speaker.

    speakerId comes from Azure Speech ConversationTranscriber
    (e.g. "Guest-1", "Guest-2", "Unknown"). Older documents without
    speakerId fall back to an unprefixed line for backward compatibility.
    """
    text = t.get("text", "")
    speaker = t.get("speakerId", "")
    if speaker:
        return f"[{speaker}] {text}"
    return text


async def notify_report_ready(interview_id: str, report_id: str) -> None:
    """Push a report-ready notification to all connected clients."""
    msg = json.dumps({"type": "report_ready", "reportId": report_id})
    for ws in _connections.get(interview_id, []):
        try:
            await ws.send_text(msg)
        except Exception:
            pass


@router.websocket("/ws/interview/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str, lang: str = Query(default="ja")):
    """Main WebSocket handler: dispatches incoming messages by type."""
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
                f"[インタビュー開始]\n\n"
                f"## インタビュー情報\n{_interview_context(interview)}\n\n"
                f"上記のインタビュー情報に基づき、最初にInterviewerが声掛けするための"
                f"内容案を related_info に記述し、最初の質問1個を suggested_questions に設定してください。"
            )
            try:
                suggestion = await asyncio.to_thread(
                    agent_service.send_message,
                    conv_id, context_msg, QUESTIONS_AGENT_NAME, lang,
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

    speaker_id = msg.get("speakerId", "") or ""

    _seq_counters[interview_id] += 1
    seq = _seq_counters[interview_id]

    doc = new_transcript_doc(interview_id, text, seq, speaker_id)
    await asyncio.to_thread(cosmos_service.create_transcript, doc)


async def _handle_supplementary(interview_id: str, msg: dict) -> None:
    """Role 1: Generate supplementary info. Fresh conversation each time.

    Aggregates the most recent transcript chunks (rolling window) and passes
    the list of already-explained keywords so the agent does not repeat
    relatedInfo for the same terms. When the agent returns no new keywords,
    nothing is sent to the clients (the UI shows nothing).
    """
    text = msg.get("text", "")
    if not text or len(text.strip()) < 10:
        return

    # Append to the rolling window of recent supplementary chunks
    chunks = _supplementary_chunks.setdefault(
        interview_id, deque(maxlen=SUPPLEMENTARY_CHUNK_WINDOW)
    )
    chunks.append(text)

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    used = _used_keywords.get(interview_id, [])

    # Per-call sections only — the role agent's SYSTEM_PROMPT contains all
    # detection / dedup / STT-correction / references-consistency rules.
    if lang == "en":
        chunk_section_header = "## Recent transcript chunks (oldest -> newest)"
        used_header = "## Already explained keywords (do NOT explain again)"
        prefix = "[Transcript / supplementary info request]"
        no_used_marker = "(none)"
    else:
        chunk_section_header = "## 直近の文字起こしチャンク（古い→新しい）"
        used_header = "## 既に説明済みのキーワード（再度説明しないこと）"
        prefix = "[文字起こし・補足情報リクエスト]"
        no_used_marker = "(なし)"

    chunks_text = "\n---\n".join(chunks)
    used_text = ", ".join(used) if used else no_used_marker

    agent_input = (
        f"{prefix}\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"{chunk_section_header}\n{chunks_text}\n\n"
        f"{used_header}\n{used_text}"
    )

    conv_id = agent_service.create_conversation()
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(
                agent_service.send_message,
                conv_id, agent_input, RELATED_INFO_AGENT_NAME, lang,
            ),
            timeout=AGENT_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("Supplementary agent call timed out for %s", interview_id)
        return
    except Exception as e:
        logger.error("Agent supplementary call failed: %s", e)
        return

    related_info = (suggestion.get("relatedInfo") or "").strip()
    new_keywords = suggestion.get("keywords", []) or []
    refs = suggestion.get("references", []) or []

    # Nothing new to show — suppress the card entirely
    if not related_info:
        return

    # Merge new keywords into the used list (case-insensitive dedup, preserve order)
    if new_keywords:
        used_lower = {k.lower() for k in _used_keywords.setdefault(interview_id, [])}
        for kw in new_keywords:
            if not kw:
                continue
            if kw.lower() not in used_lower:
                _used_keywords[interview_id].append(kw)
                used_lower.add(kw.lower())

    for ws in _connections.get(interview_id, []):
        await ws.send_text(json.dumps({
            "type": "agent_suggestion",
            "relatedInfo": related_info,
            "suggestedQuestions": [],
            "references": refs,
        }, ensure_ascii=False))
        if refs:
            await ws.send_text(json.dumps({
                "type": "agent_references", "references": refs,
            }, ensure_ascii=False))


async def _handle_generate_questions(interview_id: str) -> None:
    """Role 2: Generate three follow-up questions anchored on the current topic.

    Uses a fresh conversation each time. The three questions (deepdive /
    broaden / challenge) MUST share the same anchor topic — they are
    differentiated by angle (depth / breadth / criticism), not by subject.
    """
    transcripts = await asyncio.to_thread(
        cosmos_service.list_transcripts, interview_id
    )
    transcript_text = "\n".join(_format_transcript_line(t) for t in transcripts)
    if not transcript_text:
        return

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    full_history = transcript_text[-QUESTIONS_HISTORY_CHARS:]
    recent_topic = transcript_text[-QUESTIONS_RECENT_CHARS:]

    # Per-call sections only — the questions agent's SYSTEM_PROMPT contains
    # the central-topic identification, type-specific scopes, and goal-
    # awareness rules.
    if lang == "en":
        history_header = "## Full transcript history (most recent portion)"
        recent_header = "## Recent dialogue (use this to identify the current topic)"
        prefix = "[Question generation request]"
    else:
        history_header = "## 文字起こし全履歴（直近部分）"
        recent_header = "## 直近の対話（中心トピック特定用）"
        prefix = "[質問生成リクエスト]"

    agent_input = (
        f"{prefix}\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"{history_header}\n{full_history}\n\n"
        f"{recent_header}\n{recent_topic}"
    )

    conv_id = agent_service.create_conversation()
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(
                agent_service.send_message,
                conv_id, agent_input, QUESTIONS_AGENT_NAME, lang,
            ),
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
    transcript_text = "\n".join(_format_transcript_line(t) for t in transcripts)

    interview = _interview_cache.get(interview_id, {})
    ctx = _interview_context(interview)
    lang = _lang_cache.get(interview_id, "ja")

    # Per-call sections only — the chat agent's SYSTEM_PROMPT contains the
    # Q&A behavior rules, meta-question handling, and the rule to NOT fall
    # into automatic terminology-explanation mode. The user's question is
    # placed both at the top (priority signal) and at the bottom (recency
    # signal) so the model anchors its response on it.
    if lang == "en":
        prefix = "[Chat question from Interviewer]"
        question_header = "## Interviewer's question"
        history_header = "## Transcript history"
        repeat_header = "## Interviewer's question (re-stated for emphasis)"
    else:
        prefix = "[Interviewerからのチャット質問]"
        question_header = "## Interviewer の質問"
        history_header = "## 文字起こし履歴"
        repeat_header = "## Interviewer の質問（再掲・最重要）"

    agent_input = (
        f"{prefix}\n\n"
        f"{question_header}\n{content}\n\n"
        f"## インタビュー情報\n{ctx}\n\n"
        f"{history_header}\n{transcript_text[-CHAT_HISTORY_CHARS:]}\n\n"
        f"{repeat_header}\n{content}"
    )

    conv_id = agent_service.create_conversation()
    try:
        suggestion = await asyncio.wait_for(
            asyncio.to_thread(
                agent_service.send_message,
                conv_id, agent_input, CHAT_AGENT_NAME, lang,
            ),
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
