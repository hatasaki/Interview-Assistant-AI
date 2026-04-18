"""Service for AI Foundry agent interaction, report generation, and embeddings."""

from __future__ import annotations

import json
import logging
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI, RateLimitError, APIStatusError

from config import AGENT_MODEL, AGENT_NAME, AZURE_AI_PROJECT_ENDPOINT, EMBEDDING_MODEL

logger = logging.getLogger(__name__)

# Singleton clients (lazy-initialized)
_project: AIProjectClient | None = None
_openai = None
_azure_openai: AzureOpenAI | None = None

# Retry configuration for rate-limited API calls
MAX_RETRIES = 5
INITIAL_BACKOFF = 10  # seconds


def _speaker_tag(t: dict) -> str:
    """Return a speaker tag like ' [Guest-1]' or empty string when absent.

    speakerId is populated by Azure Speech ConversationTranscriber
    (e.g. "Guest-1", "Guest-2", "Unknown"). Older transcript documents
    without this field fall back to no tag.
    """
    speaker = t.get("speakerId", "")
    return f" [{speaker}]" if speaker else ""


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

# ── Agent system prompt (JSON output for real-time interview assistance) ──
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
      "type": "deepdive|broaden|challenge",
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

# ── Report prompt template (Japanese) ──
REPORT_PROMPT_TEMPLATE = """\
以下のインタビューの文字起こしデータから、エキスパートの暗黙知・ノウハウを最大限に抽出したレポートを生成してください。

## 最重要ルール
- レポートの内容は、必ず下記の「会話履歴」に記載された文字起こしの内容のみに基づくこと
- 文字起こしに含まれていない情報を追加・捏造しないこと
- エキスパートが「当たり前」と思って簡潔に語った部分こそ、暗黙知の宝庫である。そこを深く掘り下げて詳細に記述すること
- 具体的な数値、手順、判断基準、例外処理、失敗談、成功パターンは一つも漏らさず記録すること

## 暗黙知抽出の観点
以下の観点でエキスパートの発言を分析し、暗黙知を抽出すること:
1. **判断基準・意思決定ロジック**: 「なぜそうするのか」「どういう時にそう判断するのか」の基準
2. **手順・プロセスの詳細**: 表には出ない実際のワークフロー、ショートカット、手順の省略
3. **例外・エッジケース対応**: 通常と異なるケースでの対処法、トラブルシューティング
4. **経験則・ヒューリスティクス**: 「経験上こうするとうまくいく」「こういう場合は要注意」
5. **失敗から得た教訓**: 過去の失敗経験とそこから学んだこと
6. **暗黙の前提条件**: エキスパートが当然と思っているが初心者が見落とす前提
7. **人脈・リソースの活用法**: 誰に聞くべきか、どこを見るべきかの知識
8. **用語・概念の実務的意味**: 教科書的定義と実務での使い方の違い

## 基本情報
- 対象者: {name} ({affiliation})
- インタビュー時間: {duration}分
- ゴール: {goal}

## 会話履歴（文字起こし・ノイズ除去済み）
{transcripts}

## エージェントが提示した質問案（参考）
{questions}

## 出力形式
以下のマークダウン形式でレポートを出力してください。各セクションは可能な限り詳細に、エキスパートの発言をできるだけ具体的に引用・再現して記述すること:

# インタビューレポート

## 基本情報
- 対象者: (名前) (所属)
- 実施日時: (日時)
- インタビュー時間: (実績時間)
- インタビューゴール: (ゴール)

## エグゼクティブサマリー
(会話全体から得られた最も重要な知見を3〜5文で要約)

## エキスパートの暗黙知・ノウハウ
### 1. (テーマ)
- **概要**: (このテーマに関してエキスパートが語った内容の要約)
- **具体的なノウハウ**: (実務で使える具体的な手法・プロセス・判断基準を箇条書きで詳述)
- **エキスパートの発言**: 「(関連する重要な発言を引用)」
- **暗黙の前提・注意点**: (初心者が見落としやすいポイント)

(会話から抽出できるテーマの数だけ繰り返す)

## 判断基準・意思決定フレームワーク
(エキスパートが示した判断基準、条件分岐、優先順位の考え方をフローチャート的に記述)

## 具体的な事例・エピソード
(会話の中で語られた具体事例、成功/失敗体験を詳しく記述)

## 主要な技術的知見
(技術的な詳細、アーキテクチャ、ツール選定の理由など)

## 会話ハイライト
(会話の中で特に重要だった発言や議論のポイントを引用付きで記録)

## 今後のアクション・推奨事項
(会話の中で言及された次のステップ、課題、推奨事項)

## 追加調査が必要な領域
(インタビューで深掘りしきれなかった、または追加確認が必要なトピック)
"""

# ── Instruction appended when English output is requested ──
ENGLISH_OUTPUT_INSTRUCTION = (
    "\n\n## Language Instruction\n"
    "You MUST output your entire response in English. "
    "All field values in the JSON (related_info, question, rationale, title) must be written in English. "
    "Keep the JSON keys unchanged."
)

# ── Report prompt template (English) ──
REPORT_PROMPT_TEMPLATE_EN = """\
Generate a report from the following interview transcript, extracting the expert's tacit knowledge and know-how as thoroughly as possible.

## Most Important Rules
- The report content MUST be based solely on the transcript in the "Conversation History" section below
- Do NOT add or fabricate information not contained in the transcript
- Parts where the expert speaks briefly about things they consider "obvious" are treasure troves of tacit knowledge. Dig deep and describe them in detail
- Record every specific number, procedure, decision criterion, exception handling, failure story, and success pattern without omission

## Tacit Knowledge Extraction Perspectives
Analyze the expert's statements from these perspectives:
1. **Decision Criteria & Logic**: Criteria for "why do it that way" and "when to make that judgment"
2. **Detailed Processes & Workflows**: Actual workflows, shortcuts, and step omissions not publicly documented
3. **Exception & Edge Case Handling**: How to deal with unusual cases, troubleshooting approaches
4. **Heuristics & Rules of Thumb**: "In my experience, this works well" / "Watch out in these cases"
5. **Lessons from Failures**: Past failures and lessons learned
6. **Implicit Assumptions**: Assumptions experts take for granted but beginners miss
7. **Network & Resource Utilization**: Who to ask, where to look
8. **Practical Meaning of Terms**: Differences between textbook definitions and practical usage

## Basic Information
- Interviewee: {name} ({affiliation})
- Interview Duration: {duration} minutes
- Goal: {goal}

## Conversation History (Transcript, noise removed)
{transcripts}

## Questions Suggested by Agent (Reference)
{questions}

## Output Format
Output the report in the following markdown format. Each section should be as detailed as possible, quoting and reproducing the expert's statements as specifically as possible:

# Interview Report

## Basic Information
- Interviewee: (Name) (Affiliation)
- Date: (Date)
- Interview Duration: (Actual duration)
- Interview Goal: (Goal)

## Executive Summary
(Summarize the most important findings from the entire conversation in 3-5 sentences)

## Expert Tacit Knowledge & Know-How
### 1. (Theme)
- **Overview**: (Summary of what the expert discussed on this theme)
- **Specific Know-How**: (Practical methods, processes, and decision criteria in bullet points)
- **Expert Quote**: "(Quote relevant important statements)"
- **Implicit Assumptions & Caveats**: (Points beginners tend to miss)

(Repeat for each theme extracted from the conversation)

## Decision Criteria & Decision-Making Framework
(Describe decision criteria, conditional branching, and prioritization approaches shown by the expert)

## Specific Cases & Episodes
(Detailed descriptions of specific cases, success/failure experiences discussed in the conversation)

## Key Technical Findings
(Technical details, architecture, tool selection rationale, etc.)

## Conversation Highlights
(Important statements and discussion points from the conversation with quotes)

## Future Actions & Recommendations
(Next steps, issues, and recommendations mentioned in the conversation)

## Areas Requiring Further Investigation
(Topics not fully explored or requiring additional confirmation)
"""

# ── Transcript curation prompt (noise removal while preserving content) ──
CURATION_PROMPT = """\
以下のインタビュー文字起こしデータをキュレーションしてください。

## 最重要ルール — 絶対に情報を削除しない
- 発話に登場したすべての名詞（人名、組織名、製品名、技術用語、地名、数値、日付等）は一つも削除せず必ず残すこと
- 具体的なエピソード、事例、判断基準、手順の説明は要約・省略せずそのまま残すこと
- 発言の意味・ニュアンスが変わるような編集は絶対にしないこと

## 除去してよいもの（これだけを除去する）
- フィラー（えー、あの、うーん、えっと、まあ、なんか 等）
- 意味のない繰り返し・言い直し（「これはあの、これは」→「これは」のような同一内容の重複のみ）
- 音声認識の明らかな誤認識と思われる意味不明な文字列
- 完全に同一の文が連続している場合のみ1回にまとめる

## 除去してはいけないもの
- 発言に含まれるすべての固有名詞・専門用語・技術用語
- 具体的な数値、バージョン番号、日付、URL
- 「〇〇の場合は△△する」のような条件分岐・判断基準の記述
- 失敗談、成功事例、エピソードの詳細
- 話者の感情・強調を示す表現（「本当に重要なのは」「絶対に」等）

## 保持するもの
- 発言者の区別がある場合はそのまま保持
- タイムスタンプがある場合は保持
- 会話の流れ・順序はそのまま維持

## 出力
- クリーンアップされたテキストのみを出力すること
- 説明や注釈は一切不要
"""

# Token limits for chunked processing of large transcripts
TOKEN_LIMIT = 100_000
CHUNK_SIZE = 90_000
OVERLAP = 10_000


def _get_project() -> AIProjectClient:
    """Return the shared AIProjectClient, creating it on first call."""
    global _project
    if _project is None:
        _project = AIProjectClient(
            endpoint=AZURE_AI_PROJECT_ENDPOINT,
            credential=DefaultAzureCredential(),
        )
    return _project


def _get_openai():
    """Return the project-scoped OpenAI client for agent and model calls."""
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
            model=AGENT_MODEL,
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
    curated_transcript: str | None = None,
) -> str:
    """Generate a markdown report with preprocessing to fit context window."""
    # 1. Use curated transcript if provided, otherwise build from raw transcripts
    if curated_transcript:
        transcript_text = curated_transcript
    else:
        transcript_text = "\n".join(
            f"[{t.get('timestamp', '')}]{_speaker_tag(t)} {t.get('text', '')}" for t in transcripts
        )
        # Denoise transcript if too large
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
        model=AGENT_MODEL,
        input=prompt,
    ))

    return response.output_text


def curate_transcript(transcripts: list[dict]) -> str:
    """Curate transcripts: remove noise and duplicate context while preserving content."""
    transcript_text = "\n".join(
        f"[{t.get('timestamp', '')}]{_speaker_tag(t)} {t.get('text', '')}" for t in transcripts
    )
    if not transcript_text:
        return ""

    estimated = _estimate_tokens(transcript_text)
    if estimated <= TOKEN_LIMIT:
        return _curate_chunk(transcript_text)

    # Chunk large transcripts
    chunk_chars = CHUNK_SIZE * 3
    overlap_chars = OVERLAP * 3
    chunks = []
    start = 0
    while start < len(transcript_text):
        end = start + chunk_chars
        chunks.append(transcript_text[start:end])
        start = end - overlap_chars

    logger.info("Transcript too large (%d est. tokens), splitting into %d chunks for curation", estimated, len(chunks))

    curated_parts = []
    for i, chunk in enumerate(chunks):
        logger.info("Curating chunk %d/%d", i + 1, len(chunks))
        curated_parts.append(_curate_chunk(chunk))

    return "\n".join(curated_parts)


def _curate_chunk(text: str) -> str:
    """Use LLM to curate a transcript chunk."""
    openai = _get_openai()
    response = _call_with_retry(lambda: openai.responses.create(
        model=AGENT_MODEL,
        input=f"{CURATION_PROMPT}\n\n{text}",
    ))
    return response.output_text


def _get_azure_openai() -> AzureOpenAI:
    """Get a direct AzureOpenAI client (non-project-scoped) for embeddings."""
    global _azure_openai
    if _azure_openai is None:
        # Extract AI Services base endpoint from project endpoint
        # e.g. "https://xxx.services.ai.azure.com/api/projects/yyy" -> "https://xxx.services.ai.azure.com"
        base = AZURE_AI_PROJECT_ENDPOINT.split("/api/projects")[0]
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        _azure_openai = AzureOpenAI(
            azure_endpoint=base,
            azure_ad_token_provider=token_provider,
            api_version="2024-10-21",
        )
    return _azure_openai


def generate_embedding(text: str) -> list[float]:
    """Generate embedding vector for the given text using the embedding model."""
    client = _get_azure_openai()
    response = _call_with_retry(lambda: client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    ))
    return response.data[0].embedding


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
        model=AGENT_MODEL,
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
            {"type": q.get("type", ""), "question": q.get("question", ""), "rationale": q.get("rationale", "")}
            for q in data.get("suggested_questions", [])
        ],
        "references": [
            {"title": r.get("title", ""), "url": r.get("url", "")}
            for r in data.get("references", [])
        ],
    }
