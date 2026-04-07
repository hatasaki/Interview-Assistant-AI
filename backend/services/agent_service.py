from __future__ import annotations

import json
import logging
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from openai import RateLimitError, APIStatusError

from config import AGENT_NAME, AZURE_AI_PROJECT_ENDPOINT

logger = logging.getLogger(__name__)

_project: AIProjectClient | None = None
_openai = None

MAX_RETRIES = 5
INITIAL_BACKOFF = 10  # seconds


def _call_with_retry(fn):
    """Call fn() with exponential backoff on 429 errors."""
    for attempt in range(MAX_RETRIES):
        try:
            return fn()
        except (RateLimitError, APIStatusError) as e:
            # APIStatusError with status 429 should also be retried
            if isinstance(e, APIStatusError) and e.status_code != 429:
                raise
            if attempt == MAX_RETRIES - 1:
                raise
            wait = INITIAL_BACKOFF * (2 ** attempt)
            logger.warning("Rate limited (attempt %d/%d), retrying in %ds", attempt + 1, MAX_RETRIES, wait)
            time.sleep(wait)

SYSTEM_PROMPT = """\
あなたはインタビュー補助 AI エージェントです。

## 最重要ルール
- あなたの入力には「[文字起こし] ...」や「[Interviewerからの補足質問] ...」というプレフィックスが付いている
- 必ずその入力テキストの内容を注意深く読み、その内容に直接関連する応答のみを返すこと
- 入力テキストと無関係な情報・質問案は絶対に返さないこと
- 入力が短い・技術的でない場合は related_info を空にし、会話の流れに沿った質問案のみ返すこと

## 役割
- エキスパート（Interviewee）の暗黙知を引き出すため、素人（Interviewer）をサポートする
- 入力テキスト中に専門用語・技術概念・製品名がある場合のみ、microsoft_docs_search で検索し素人向け補足説明する
- 会話の流れに基づいた次の質問案を提示する
- 専門用語には必ず平易な説明を付ける

## 出力形式
以下を JSON 形式で返す:
{
  "related_info": "入力に含まれる専門用語の補足説明。説明文中の専門用語や概念名にはマークダウン形式のリンクを埋め込むこと（例: [CAF](https://learn.microsoft.com/azure/cloud-adoption-framework/)）。なければ空文字列",
  "suggested_questions": [
    {
      "question": "会話の流れに基づく次の質問",
      "rationale": "なぜこの質問が重要か"
    }
  ],
  "references": [
    {
      "title": "参照元ドキュメントタイトル",
      "url": "https://learn.microsoft.com/..."
    }
  ]
}
必ず有効な JSON のみを出力し、他のテキストは含めないこと。
"""

REPORT_PROMPT_TEMPLATE = """\
以下のインタビューの文字起こしデータからレポートを生成してください。

## 最重要ルール
- レポートの内容は、必ず下記の「会話履歴」に記載された文字起こしの内容のみに基づくこと
- 文字起こしに含まれていない情報を追加・捏造しないこと
- 会話で言及されていない技術、製品、事例をレポートに含めないこと
- 不明な点は「会話では言及されなかった」と記載すること

## 基本情報
- 対象者: {name} ({affiliation})
- インタビュー時間: {duration}分
- ゴール: {goal}

## 会話履歴（文字起こし・ノイズ除去済み）
{transcripts}

## エージェントが提示した質問案（参考）
{questions}

## 出力形式
以下のマークダウン形式でレポートを出力してください。各セクションの内容は必ず上記の会話履歴から抽出すること:

# インタビューレポート

## 基本情報
- 対象者: (名前) (所属)
- 実施日時: (日時)
- インタビュー時間: (実績時間)
- インタビューゴール: (ゴール)

## エグゼクティブサマリー
(会話内容の要約。会話に含まれる内容のみ)

## 主要な知見
### 知見 1: (タイトル)
(会話から得られた具体的な知見の詳細)

## 会話ハイライト
(会話の中で特に重要だった発言や議論のポイント)

## 今後のアクション・推奨事項
(会話の中で言及された次のステップや課題)
"""

ENGLISH_OUTPUT_INSTRUCTION = (
    "\n\n## Language Instruction\n"
    "You MUST output your entire response in English. "
    "All field values in the JSON (related_info, question, rationale, title) must be written in English. "
    "Keep the JSON keys unchanged."
)

REPORT_PROMPT_TEMPLATE_EN = """\
Generate a report from the following interview transcript data.

## Most Important Rules
- The report content MUST be based solely on the transcript in the "Conversation History" section below
- Do NOT add or fabricate information not contained in the transcript
- Do NOT include technologies, products, or examples not mentioned in the conversation
- For unclear points, state "This was not discussed in the conversation"

## Basic Information
- Interviewee: {name} ({affiliation})
- Interview Duration: {duration} minutes
- Goal: {goal}

## Conversation History (Transcript, noise removed)
{transcripts}

## Questions Suggested by Agent (Reference)
{questions}

## Output Format
Output the report in the following markdown format. All section content must be extracted from the conversation history above:

# Interview Report

## Basic Information
- Interviewee: (Name) (Affiliation)
- Date: (Date)
- Interview Duration: (Actual duration)
- Interview Goal: (Goal)

## Executive Summary
(Summary of the conversation content. Only content from the conversation.)

## Key Findings
### Finding 1: (Title)
(Details of specific findings obtained from the conversation)

## Conversation Highlights
(Key statements and discussion points from the conversation)

## Future Actions & Recommendations
(Next steps and issues mentioned in the conversation)
"""

TOKEN_LIMIT = 100_000
CHUNK_SIZE = 90_000
OVERLAP = 10_000


def _get_project() -> AIProjectClient:
    global _project
    if _project is None:
        _project = AIProjectClient(
            endpoint=AZURE_AI_PROJECT_ENDPOINT,
            credential=DefaultAzureCredential(),
        )
    return _project


def _get_openai():
    global _openai
    if _openai is None:
        _openai = _get_project().get_openai_client()
    return _openai


def ensure_agent() -> None:
    """Create or update the interview-assistant agent."""
    project = _get_project()
    logger.info("Creating/updating agent '%s'", AGENT_NAME)
    mcp_tool = MCPTool(
        server_label="microsoft_learn",
        server_url="https://learn.microsoft.com/api/mcp",
        require_approval="never",
    )
    project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model="gpt-4o",
            instructions=SYSTEM_PROMPT,
            tools=[mcp_tool],
        ),
    )
    logger.info("Agent '%s' created/updated", AGENT_NAME)


def create_conversation() -> str:
    """Create a new conversation and return its ID."""
    openai = _get_openai()
    conversation = openai.conversations.create()
    return conversation.id


def send_message(conversation_id: str, message: str, lang: str = "ja") -> dict:
    """Send a message to the agent and return parsed suggestion."""
    if lang == "en":
        message = message + ENGLISH_OUTPUT_INSTRUCTION

    openai = _get_openai()
    response = _call_with_retry(lambda: openai.responses.create(
        conversation=conversation_id,
        input=message,
        extra_body={
            "agent_reference": {"name": AGENT_NAME, "type": "agent_reference"}
        },
    ))

    raw_text = response.output_text

    return _parse_agent_response(raw_text)


def generate_report(
    interview: dict,
    transcripts: list[dict],
    agent_responses: list[dict],
    chat_messages: list[dict],
    lang: str = "ja",
) -> str:
    """Generate a markdown report with preprocessing to fit context window."""
    # 1. Build raw transcript text
    transcript_text = "\n".join(
        f"[{t.get('timestamp', '')}] {t.get('text', '')}" for t in transcripts
    )

    # 2. Denoise transcript if too large
    transcript_text = _denoise_transcript(transcript_text)

    # 3. Extract only questions from agent responses (drop relatedInfo)
    questions = _extract_questions(agent_responses)

    # 4. Generate report using direct model call (not agent) to get markdown output
    template = REPORT_PROMPT_TEMPLATE_EN if lang == "en" else REPORT_PROMPT_TEMPLATE
    none_text = "(None)" if lang == "en" else "(なし)"
    prompt = template.format(
        name=interview.get("intervieweeName", ""),
        affiliation=interview.get("intervieweeAffiliation", ""),
        duration=interview.get("durationMinutes", ""),
        goal=interview.get("goal", ""),
        transcripts=transcript_text or none_text,
        questions=questions or none_text,
    )

    openai = _get_openai()
    response = _call_with_retry(lambda: openai.responses.create(
        model="gpt-4o",
        input=prompt,
    ))

    return response.output_text


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 3 chars for Japanese."""
    return len(text) // 3


def _denoise_transcript(text: str) -> str:
    """Denoise transcript, chunking if it exceeds TOKEN_LIMIT."""
    if not text:
        return text

    estimated = _estimate_tokens(text)
    if estimated <= TOKEN_LIMIT:
        # Small enough — single-pass denoise
        return _denoise_chunk(text)

    # Chunk by character count (3 chars ≈ 1 token)
    chunk_chars = CHUNK_SIZE * 3
    overlap_chars = OVERLAP * 3
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_chars
        chunks.append(text[start:end])
        start = end - overlap_chars

    logger.info("Transcript too large (%d est. tokens), splitting into %d chunks", estimated, len(chunks))

    denoised_parts = []
    for i, chunk in enumerate(chunks):
        logger.info("Denoising chunk %d/%d", i + 1, len(chunks))
        denoised_parts.append(_denoise_chunk(chunk))

    return "\n".join(denoised_parts)


def _denoise_chunk(text: str) -> str:
    """Use LLM to remove noise from a transcript chunk."""
    openai = _get_openai()
    response = _call_with_retry(lambda: openai.responses.create(
        model="gpt-4o",
        input=(
            "以下のインタビュー文字起こしからノイズを除去してください。\n"
            "- フィラー（えー、あの、うーん等）、意味のない繰り返し、誤認識を削除\n"
            "- 会話の原文・内容はできるだけそのまま残す\n"
            "- タイムスタンプは保持する\n"
            "- 出力はクリーンアップされたテキストのみ（説明不要）\n\n"
            f"{text}"
        ),
    ))
    return response.output_text


def _extract_questions(agent_responses: list[dict]) -> str:
    """Extract only suggested questions from agent responses."""
    questions = []
    for resp in agent_responses:
        for q in resp.get("suggestedQuestions", []):
            question = q.get("question", "")
            if question:
                questions.append(f"- {question}")
    return "\n".join(questions) if questions else ""


def _parse_agent_response(raw: str) -> dict:
    """Parse agent JSON response, tolerating markdown fences."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = {
            "related_info": raw,
            "suggested_questions": [],
            "references": [],
        }

    return {
        "relatedInfo": data.get("related_info", ""),
        "suggestedQuestions": [
            {"question": q.get("question", ""), "rationale": q.get("rationale", "")}
            for q in data.get("suggested_questions", [])
        ],
        "references": [
            {"title": r.get("title", ""), "url": r.get("url", "")}
            for r in data.get("references", [])
        ],
    }
