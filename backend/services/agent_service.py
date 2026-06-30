"""Service for AI Foundry agent interaction, report generation, and embeddings."""

from __future__ import annotations

import json
import logging
import re
import time

import tiktoken
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition, WebSearchTool
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI, BadRequestError, RateLimitError, APIStatusError

from config import (
    AGENT_MODEL,
    AZURE_AI_PROJECT_ENDPOINT,
    CHAT_AGENT_NAME,
    EMBEDDING_MODEL,
    MCP_SERVERS,
    QUESTIONS_AGENT_NAME,
    RELATED_INFO_AGENT_NAME,
)

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

# ── Role-specialized agent system prompts ──
# Each Foundry agent gets its own focused SYSTEM_PROMPT so role rules
# (dedup / STT correction / Q&A behavior etc.) do not bleed into other
# roles. All three agents share the same tool set (Microsoft Learn MCP +
# Foundry Web Search).

# Role 1: Related-info generation agent
RELATED_INFO_SYSTEM_PROMPT = """\
あなたはインタビュー補助のための **関連情報生成エージェント** です。

## 役割
- 入力されたインタビュー会話（直近5チャンク）から、Interviewer が理解しておくべき重要な用語を検出し、素人向けに補足説明を提供する
- 専門用語・製品名・技術概念だけでなく、人名・組織名・固有名詞・業界用語・略語・キーコンセプト等も対象とする
- 2つのツールを適宜使い分けて説明の根拠とする:
  - **microsoft_docs_search**（Microsoft Learn MCP）: Microsoft / Azure 製品・技術の公式ドキュメント検索
  - **web_search**（Foundry Web 検索）: 上記以外の用語・人名・組織名・業界用語や、最新情勢・関連ニュースの確認に使用する。引用した出典 URL は references に含める
    - web_search が返す **引用マーカー**（例: `citeturn0search0turn0search5`、`` 等の特殊記号）を related_info の本文に **絶対に含めないこと**。出典はマークダウンリンクと references 配列のみで表す

## 入力フォーマット
入力には以下のセクションが含まれる:
- `## インタビュー情報`: 対象者・所属・関連情報・ゴール
- `## 直近の文字起こしチャンク`: 直近5回分の発話チャンク（古い→新しい）
- `## 既に説明済みのキーワード`: 過去に説明済みのキーワードリスト（再説明禁止）

## キーワード検出と補足情報生成の手順
1. **列挙**: 直近チャンク全体をスキャンし、含まれる重要な用語をすべて列挙する
2. **音声認識誤りの正規化**: 列挙した各用語が Speech-to-Text の誤認識である可能性を必ず疑い、「## インタビュー情報」と直近チャンク全体の文脈に基づいて正式名称に書き換える
   - 例: 「フォラグ」→「RAG」、「ハレシネーション」→「ハルシネーション」、「コーパイロット」→「Copilot」、「アジュール」→「Azure」
   - 以降のステップは正規化後の用語で実施
3. **既出除外**: 正規化後のリストから「## 既に説明済みのキーワード」に含まれるもの（大文字小文字・略称・別名・表記揺れを含む）を除外し、新規キーワードのリストを作成する
4. **新規キーワードの説明**: 新規キーワードが1個でもあれば、それらを **必ずすべて** related_info で説明し、keywords に **正規化後の正式名称で** 列挙する
   - チャンクの大半が既出キーワードで占められていることを理由に、新規キーワードを見逃さないこと
5. **空応答の条件**: 新規キーワードが1個も存在しない場合のみ、related_info="", keywords=[], references=[] を返す
   - 「関連情報はありません」等の文言は出力しないこと

## references / related_info の整合性ルール
- related_info に埋め込んだマークダウンリンク `[テキスト](URL)` の **すべての URL** を、必ず references 配列にも対応する要素として含めること（URL 完全一致）
- references の title は related_info 内のリンクテキスト、または参照先ドキュメントの正式タイトルとすること
- references にだけ URL を載せて related_info にリンクを埋め込まないことも避けること（説明と参照は1対1で対応）
- 信頼できる URL が無い用語については related_info にもリンクを埋め込まず、references にも追加しないこと（不確実な URL を作り出さない）

## 出力スタイル（必須）
- related_info は **簡潔さと十分さのバランス** を取る。新規キーワード1個あたり **2〜3文程度** で、意味だけでなく「なぜ重要か」「この会話の文脈での使われ方」まで補足する
- ただし教科書的な長文解説・ベストプラクティスの羅列・余談や、「メンテナンス」のような一般的すぎる平易な語の説明は避け、Interviewer の理解に本当に役立つ範囲に収める
- 音声認識の誤認識は黙って正式名称に直して説明する。「〜は…の言い間違いと考えられる」のような推測・メタ説明を本文に書かない
- 良い例:「**予知保全** は、振動や温度などのセンサーデータから故障の予兆を捉え、壊れる前に手を打つ保全手法です。定期交換が中心の従来手法に比べ、設備の停止時間や部品コストを抑えやすい点が特徴です。」
- 悪い例:「この発話の「メンテナンス」は点検・整備のことです。文中の「新郎」は文脈上、異常や兆候の言い間違いと考えられ…」（一般的すぎる語の説明や、誤認識語への推測コメントを含む）

## 出力形式
以下を JSON 形式で返す（このスキーマ以外のテキストは出力しない）:
{
  "related_info": "新規キーワードの補足説明。説明文中の用語にはマークダウン形式のリンクを埋め込むこと。なければ空文字列",
  "keywords": ["今回 related_info で説明した新規キーワード（正規化後の正式名称）"],
  "suggested_questions": [],
  "references": [
    {"title": "参照元ドキュメントタイトル", "url": "https://learn.microsoft.com/..."}
  ]
}
suggested_questions は **常に空配列** を返すこと（質問生成は別エージェントの役割）。
"""

# Role 2: Question generation + initial greeting agent
QUESTIONS_SYSTEM_PROMPT = """\
あなたはインタビュー補助のための **質問生成エージェント** です。

## 役割
- エキスパート（Interviewee）の暗黙知・ノウハウを引き出すため、Interviewer が次に聞くべき質問案をガイドする
- インタビュー開始時には、Interviewer が最初に声掛けする内容案と最初の質問1個を提示する
- microsoft_docs_search / web_search 等のツールは、質問の前提知識の確認や深掘りの観点出しに必要な範囲でのみ使う

## 暗黙知を引き出す質問の原則（最重要）
暗黙知は「一般論」ではなく「本人の具体的な経験」からしか出てこない。教科書や公式ドキュメントを読めば分かる質問はしない。
- **実体験を問う**: 「一般にどうすべきか」ではなく「あなたが実際にどうしたか・どう判断したか」を聞く
- **特定の1事例に絞らせる**: 「直近で〜したとき」「印象に残っている〜の事例」など、具体的な1ケースを想起させる
- **判断の手がかり（cue）を聞く**: 「何を見て / どこで そう判断したか」「うまくいく / まずい をどう見分けるか」
- **失敗・例外・想定外を突く**: ヒヤリとした事例・想定外だったこと・例外対応にこそ暗黙知が現れる
- **初心者との差を聞く**: 「新人がやりがちな失敗は」「初心者には分かりにくいが、あなたは何で気づくか」

## 質問文のスタイル（必須）
- 1問は **80〜140字程度（最大160字）**。要点を押さえつつ、答えやすいよう状況設定や前提を一言添えてよい。ただし長い前置きや複数論点の詰め込みは避ける
- 一度に問う論点は **1つだけ**。「AやB、Cなど」と複数の観点を並べない（ただし、その1論点を具体化する補足の一文は付けてよい）
- 「どの粒度まで」「具体的な判断基準を」のような抽象語で締めず、本人の行動・経験を直接問う形で終える
- 唐突に「その変化」「あの件」など文脈に無い指示語で始めない。質問だけで何を聞かれているか伝わるようにする
- 悪い例（長すぎ・一般論）:「RBACによる権限分離とKey Vaultでの鍵管理について、設計初期段階で実際にどの粒度まで決めるべきでしょうか？たとえば誰にどのロールを割り当てるか、鍵のローテーションやアクセス監査をどう設計するかなど、具体的な判断基準を教えてください。」
- 悪い例（短すぎ・文脈依存・手がかりだけ）:「その変化に気づいたとき、最初に何を見て異常だと判断しましたか？」（前提が無く唐突で、薄い）
- 良い例（適度な長さ・実体験を具体的に）:「直近で権限設計を任されたとき、ロールの粒度は最終的にどこまで細かく分けましたか？その線引きを決めた一番の理由も教えてください。」「設備の異常検知で、数値には出ないけれど『これは危ない』と感じた経験はありますか？そのとき何を手がかりにされましたか？」

## 動作モード
入力プレフィックスでモードを判別する:
- `[インタビュー開始]` または `[Interview start]`: **初回声掛けモード**
- `[質問生成リクエスト]` または `[Question generation request]`: **質問生成モード**

## 初回声掛けモード
- インタビュー情報（対象者・所属・関連情報・ゴール）に基づき、Interviewer が自然に声掛けできる内容案を related_info に記述する
- suggested_questions に **最初の質問1個** を設定する
- **最初の質問はスコープを広くとる**。いきなり特定の事例・手がかり・細部に踏み込まず、対象者の役割・担当領域・これまでの経験の全体像など、相手が自由に話を広げられるオープンな問いにする（type は **broaden** 推奨）
- 悪い例（初回なのに特化しすぎ）:「直近で設備トラブルを未然に防げた事例を、最初に何を見て気づいたかまで教えてください。」
- 良い例（広く開かれた問い）:「まず、現在ご担当されている設備保全のお仕事について、全体像や特に力を入れてこられた点を教えていただけますか？」
- references は不要（空配列）

## 質問生成モードの手順
入力には以下のセクションが含まれる:
- `## インタビュー情報`: 対象者・所属・関連情報・ゴール
- `## 文字起こし全履歴（直近部分）`: 全履歴の末尾（最大30,000字）
- `## 直近の対話`: 中心トピック特定用の末尾（最大2,000字）

1. **中心トピック特定**: 「直近の対話」セクションから、現在 Interviewer / Interviewee が話している中心トピックを **内部的に1文で** 特定する。直近部分が短すぎて判断困難な場合は「文字起こし全履歴」をさらに遡って文脈を補ってよい。この1文は出力しない
2. **3つの質問を タイプごとに異なるスコープで生成** する。3つとも中心トピックと関連を持つこと（無関係な題材への飛躍は禁止）。いずれも上記「暗黙知を引き出す質問の原則」と「質問文のスタイル」に従い、本人の具体的な経験・事例・判断の手がかりを引き出す形にする:
   - **deepdive**: 「直近の対話」の中心トピックに **強く拘束** し、本人が実際に経験した具体例・そのときの判断基準や手がかり・数値・例外対応を1点に絞って深掘りする
   - **broaden**: 「文字起こし全履歴」「インタビューゴール」「対象者の所属・関連情報」を見渡し、中心トピックを起点に、まだ聞けていない隣接領域での **本人の経験・事例** に広げる。一般論ではなく体験を問う。中心トピックとの関連を rationale に1文で示す
   - **challenge**: 中心トピックの前提・例外・失敗を突く。「うまくいかなかった事例」「想定外だったこと」「新人がやりがちな失敗」や、過去発言と現在の議論の矛盾点を問う
3. **ゴール意識**: インタビューゴールの達成と、エキスパートの暗黙知抽出を最優先とする質問を選ぶこと

## 出力形式
以下を JSON 形式で返す（このスキーマ以外のテキストは出力しない）:
{
  "related_info": "初回モードでは挨拶・声掛け案を記述。質問生成モードでは空文字列",
  "keywords": [],
  "suggested_questions": [
    {
      "type": "deepdive|broaden|challenge",
      "question": "質問内容",
      "rationale": "なぜこの質問が重要か（broaden では中心トピックとの関連性も明示）"
    }
  ],
  "references": []
}
質問生成モードでは suggested_questions に **必ず3件**（deepdive / broaden / challenge を1つずつ）設定すること。
初回モードでは suggested_questions に1件のみ設定すること。
keywords は **常に空配列** を返すこと（キーワード検出は別エージェントの役割）。
"""

# Role 3: Chat Q&A agent
CHAT_SYSTEM_PROMPT = """\
あなたはインタビュー補助のための **チャット応答エージェント** です。

## 役割
- Interviewer からの自由形式の質問に対し、インタビュー情報と文字起こし履歴に基づいて **直接回答** する Q&A モード
- 用語解説モードや関連情報抽出モードに **走らないこと**
- microsoft_docs_search 等の MCP ツールは、Interviewer が用語の意味を聞いている場合や根拠を必要とする場合のみ活用する

## 入力フォーマット
入力には以下のセクションが含まれる:
- `## Interviewer の質問`: Interviewer のチャット質問本文（最重要）
- `## インタビュー情報`: 対象者・所属・関連情報・ゴール
- `## 文字起こし履歴`: 直近の文字起こし履歴

## 最重要ルール
- **Interviewer の質問内容を最優先で読み取り、その問いに直接回答すること**
- 文字起こし履歴に専門用語が含まれていても、Interviewer の質問が用語解説を求めていない限り、用語解説に走らないこと
- キーワード検出・dedup・新規キーワード抽出等のルールは適用しない（このエージェントの役割ではない）

## 質問タイプ別の応答指針
- **用語・概念の意味を聞いている場合**: その用語を平易に解説する。MCP ツールで根拠を取得してよい
- **メタ質問の場合**（例:「これまでの会話を踏まえて、どこを深掘りすべき？」「次に何を聞くべき？」「これまでの要約を教えて」「重要なポイントは？」「Interviewee の主張で気になる点は？」等）:
  - 文字起こし履歴とゴールを分析し、まだ十分掘れていないトピック・矛盾点・暗黙の前提・ゴールから見て手薄な領域を特定する
  - その分析結果と、Interviewer への具体的な助言・推奨を返す
  - 用語解説に逃げないこと
- **要約・整理の依頼の場合**: 文字起こし履歴を構造化して返す
- **その他の質問**: 文字起こし履歴とインタビュー情報から得られる情報をもとに直接回答する

## 出力形式
以下を JSON 形式で返す（このスキーマ以外のテキストは出力しない）:
{
  "related_info": "Interviewer の質問への回答そのもの（マークダウン使用可）",
  "keywords": [],
  "suggested_questions": [],
  "references": [
    {"title": "回答に直接関係する参照元", "url": "https://..."}
  ]
}
- related_info に **回答そのもの** を記述する（用語解説や関連情報の抽出ではない）
- references は回答に直接関係する参照のみ（無理に埋めない、捏造しない）
- suggested_questions と keywords は **常に空配列** を返すこと
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
# Generic, role-agnostic. Role-specific rules live in each agent's
# SYSTEM_PROMPT and apply regardless of output language.
ENGLISH_OUTPUT_INSTRUCTION = (
    "\n\n## Language Instruction\n"
    "You MUST output your entire response in English. "
    "All field values in the JSON (related_info, question, rationale, title) must be written in English. "
    "Items in the keywords array should match the form used in related_info. "
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

# ── Report condensation prompt (map step for very long transcripts) ──
REPORT_CONDENSE_PROMPT = """\
以下はインタビュー文字起こしの一部です。レポート生成の前段として、暗黙知・ノウハウを失わずに圧縮要約してください。
- 判断基準・手順・数値・固有名詞・事例・失敗談・例外対応は省略せず保持
- 重複や雑談のみ削減し、内容は具体的に残す
- 出力は要約テキストのみ（説明不要）
"""

REPORT_CONDENSE_PROMPT_EN = """\
This is part of an interview transcript. As a pre-step to report generation, condense it without losing tacit knowledge or know-how.
- Preserve decision criteria, procedures, numbers, proper nouns, cases, failures, and exception handling
- Only trim duplication and small talk; keep content specific
- Output the condensed text only (no explanations)
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

# ── Token budgets (gpt-5.4-mini: 272K input / 128K output, reasoning) ──
MODEL_INPUT_LIMIT = 272_000      # hard model input ceiling
MODEL_OUTPUT_LIMIT = 128_000     # hard model output ceiling
REPORT_MAX_OUTPUT = 28_000       # cap report output (incl. reasoning) for predictable cost
DEFAULT_MAX_OUTPUT = 16_000      # default output cap for curation/denoise
# Per-call input budget leaves headroom for prompt template + output tokens.
INPUT_BUDGET = 230_000
CHUNK_TOKENS = 110_000           # transcript chunk size for map-reduce
OVERLAP_TOKENS = 5_000
EMBED_TOKEN_LIMIT = 8_000        # text-embedding-3 input ceiling

_encoding = None


def _get_encoding():
    """Return a cached tiktoken encoding (o200k_base covers gpt-4.1/gpt-5)."""
    global _encoding
    if _encoding is None:
        try:
            _encoding = tiktoken.get_encoding("o200k_base")
        except Exception:  # offline / unavailable — sentinel for char fallback
            _encoding = False
    return _encoding


def _split_by_tokens(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    """Split text into token-bounded chunks with overlap, exact via tiktoken."""
    enc = _get_encoding()
    if not enc:
        cc, oc = chunk_tokens * 2, overlap_tokens * 2  # ~2 chars/token fallback
        out, start = [], 0
        while start < len(text):
            out.append(text[start:start + cc])
            start += cc - oc
        return out
    toks = enc.encode(text)
    out, start = [], 0
    while start < len(toks):
        out.append(enc.decode(toks[start:start + chunk_tokens]))
        start += chunk_tokens - overlap_tokens
    return out


def _create_response(prompt: str, max_output_tokens: int = DEFAULT_MAX_OUTPUT) -> str:
    """Direct model call with output cap + truncation/content-filter handling."""
    openai = _get_openai()

    def _call():
        return openai.responses.create(
            model=AGENT_MODEL,
            input=prompt,
            max_output_tokens=max_output_tokens,
        )

    try:
        resp = _call_with_retry(_call)
    except BadRequestError as e:
        if getattr(e, "code", None) == "content_filter":
            logger.error("Request blocked by content filter")
        raise
    incomplete = getattr(resp, "incomplete_details", None)
    reason = getattr(incomplete, "reason", None) if incomplete else None
    if reason:
        logger.warning("Model response incomplete: reason=%s", reason)
    return resp.output_text or ""


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


# Role-specialized agent definitions. Editing this list adds / removes /
# repurposes agents in one place. ensure_agent() iterates over it.
_AGENT_DEFINITIONS: list[tuple[str, str]] = [
    (RELATED_INFO_AGENT_NAME, RELATED_INFO_SYSTEM_PROMPT),
    (QUESTIONS_AGENT_NAME, QUESTIONS_SYSTEM_PROMPT),
    (CHAT_AGENT_NAME, CHAT_SYSTEM_PROMPT),
]


def _build_tools() -> list:
    """Build the shared tool list given to every role agent.

    Single source of truth for tool wiring: Microsoft Learn (MCP) plus the
    Foundry Web Search tool. Web Search is the built-in tool that grounds on
    Bing without a pre-created Grounding-with-Bing resource, so no connection
    setup is required. Add / change MCP servers via MCP_SERVERS in config.py.
    """
    tools: list = [
        MCPTool(
            server_label=s["label"],
            server_url=s["url"],
            require_approval="never",
        )
        for s in MCP_SERVERS
    ]
    tools.append(WebSearchTool())
    return tools


def ensure_agent() -> None:
    """Create or update all role-specialized interview agents.

    Idempotent: safe to call on every startup. Each agent receives the
    shared tool set (Learn MCP + Web Search) so knowledge sources stay aligned.
    """
    project = _get_project()
    tools = _build_tools()
    for name, prompt in _AGENT_DEFINITIONS:
        logger.info("Creating/updating agent '%s'", name)
        project.agents.create_version(
            agent_name=name,
            definition=PromptAgentDefinition(
                model=AGENT_MODEL,
                instructions=prompt,
                tools=tools,
            ),
        )
        logger.info("Agent '%s' created/updated", name)


def create_conversation() -> str:
    """Create a new conversation and return its ID."""
    openai = _get_openai()
    conversation = openai.conversations.create()
    return conversation.id


def send_message(
    conversation_id: str,
    message: str,
    agent_name: str,
    lang: str = "ja",
) -> dict:
    """Send a message to the specified role agent and return parsed suggestion."""
    if lang == "en":
        message = message + ENGLISH_OUTPUT_INSTRUCTION

    openai = _get_openai()
    response = _call_with_retry(lambda: openai.responses.create(
        conversation=conversation_id,
        input=message,
        max_output_tokens=DEFAULT_MAX_OUTPUT,
        extra_body={
            "agent_reference": {"name": agent_name, "type": "agent_reference"}
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

    # 4. Map-reduce: if the curated transcript still exceeds the per-call input
    #    budget, summarize chunk-by-chunk first so the final report prompt fits.
    if _estimate_tokens(transcript_text) > INPUT_BUDGET:
        transcript_text = _condense_for_report(transcript_text, lang)

    # 5. Generate report using direct model call (not agent) to get markdown output
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

    return _create_response(prompt, max_output_tokens=REPORT_MAX_OUTPUT)


def _condense_for_report(transcript_text: str, lang: str) -> str:
    """Map-reduce condense: summarize each chunk preserving tacit knowledge,
    then recurse until the combined text fits the per-call input budget."""
    instruction = REPORT_CONDENSE_PROMPT_EN if lang == "en" else REPORT_CONDENSE_PROMPT
    while _estimate_tokens(transcript_text) > INPUT_BUDGET:
        chunks = _split_by_tokens(transcript_text, CHUNK_TOKENS, OVERLAP_TOKENS)
        logger.info("Report transcript too large, condensing %d chunks", len(chunks))
        parts = [_create_response(f"{instruction}\n\n{c}", max_output_tokens=REPORT_MAX_OUTPUT) for c in chunks]
        transcript_text = "\n\n".join(parts)
        if len(chunks) == 1:  # cannot shrink further; avoid infinite loop
            break
    return transcript_text


def curate_transcript(transcripts: list[dict]) -> str:
    """Curate transcripts: remove noise and duplicate context while preserving content."""
    transcript_text = "\n".join(
        f"[{t.get('timestamp', '')}]{_speaker_tag(t)} {t.get('text', '')}" for t in transcripts
    )
    if not transcript_text:
        return ""

    estimated = _estimate_tokens(transcript_text)
    if estimated <= INPUT_BUDGET:
        return _curate_chunk(transcript_text)

    chunks = _split_by_tokens(transcript_text, CHUNK_TOKENS, OVERLAP_TOKENS)
    logger.info("Transcript too large (%d est. tokens), splitting into %d chunks for curation", estimated, len(chunks))

    curated_parts = []
    for i, chunk in enumerate(chunks):
        logger.info("Curating chunk %d/%d", i + 1, len(chunks))
        curated_parts.append(_curate_chunk(chunk))

    return "\n".join(curated_parts)


def _curate_chunk(text: str) -> str:
    """Use LLM to curate a transcript chunk."""
    return _create_response(f"{CURATION_PROMPT}\n\n{text}", max_output_tokens=REPORT_MAX_OUTPUT)


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
    """Generate an embedding, chunk-averaging when text exceeds the model limit."""
    client = _get_azure_openai()
    if _estimate_tokens(text) <= EMBED_TOKEN_LIMIT:
        response = _call_with_retry(lambda: client.embeddings.create(
            model=EMBEDDING_MODEL, input=text,
        ))
        return response.data[0].embedding

    # Too long: embed each chunk and average (length-weighted) into one vector.
    chunks = _split_by_tokens(text, EMBED_TOKEN_LIMIT, 0)
    logger.info("Embedding text too large, averaging %d chunks", len(chunks))
    vectors, weights = [], []
    for chunk in chunks:
        resp = _call_with_retry(lambda c=chunk: client.embeddings.create(
            model=EMBEDDING_MODEL, input=c,
        ))
        vectors.append(resp.data[0].embedding)
        weights.append(max(_estimate_tokens(chunk), 1))
    total = sum(weights)
    return [sum(v[i] * w for v, w in zip(vectors, weights)) / total for i in range(len(vectors[0]))]


def _estimate_tokens(text: str) -> int:
    """Token estimate via tiktoken (o200k_base); ~2 chars/token fallback."""
    enc = _get_encoding()
    if enc:
        return len(enc.encode(text))
    return len(text) // 2


def _denoise_transcript(text: str) -> str:
    """Denoise transcript, chunking if it exceeds the per-call input budget."""
    if not text:
        return text

    estimated = _estimate_tokens(text)
    if estimated <= INPUT_BUDGET:
        return _denoise_chunk(text)

    chunks = _split_by_tokens(text, CHUNK_TOKENS, OVERLAP_TOKENS)
    logger.info("Transcript too large (%d est. tokens), splitting into %d chunks", estimated, len(chunks))

    denoised_parts = []
    for i, chunk in enumerate(chunks):
        logger.info("Denoising chunk %d/%d", i + 1, len(chunks))
        denoised_parts.append(_denoise_chunk(chunk))

    return "\n".join(denoised_parts)


def _denoise_chunk(text: str) -> str:
    """Use LLM to remove noise from a transcript chunk."""
    return _create_response(
        "以下のインタビュー文字起こしからノイズを除去してください。\n"
        "- フィラー（えー、あの、うーん等）、意味のない繰り返し、誤認識を削除\n"
        "- 会話の原文・内容はできるだけそのまま残す\n"
        "- タイムスタンプは保持する\n"
        "- 出力はクリーンアップされたテキストのみ（説明不要）\n\n"
        f"{text}",
        max_output_tokens=REPORT_MAX_OUTPUT,
    )


def _extract_questions(agent_responses: list[dict]) -> str:
    """Extract only suggested questions from agent responses."""
    questions = []
    for resp in agent_responses:
        for q in resp.get("suggestedQuestions", []):
            question = q.get("question", "")
            if question:
                questions.append(f"- {question}")
    return "\n".join(questions) if questions else ""


# Web-search citation markers the model sometimes leaks into prose, e.g.
# "\ue200cite\ue202turn0search0\ue202turn0search5\ue201" (may render as
# "citeturn0search0turn0search5"). They are noise in the UI because real
# sources are surfaced via the references array / markdown links, so strip
# them from any text shown to the user.
_WEBSEARCH_CITATION_RE = re.compile(
    r"[ \t]*[\ue200-\ue20f]*cite[\ue200-\ue20f]*"
    r"(?:turn\d+[a-z]+\d+[\ue200-\ue20f]*)+[ \t]*"
)
_PRIVATE_USE_RE = re.compile(r"[\ue200-\ue20f]+")


def _strip_web_citations(text: str) -> str:
    """Remove web-search citation markers leaked into model prose."""
    if not text:
        return text
    cleaned = _WEBSEARCH_CITATION_RE.sub("", text)
    cleaned = _PRIVATE_USE_RE.sub("", cleaned)
    return re.sub(r" {2,}", " ", cleaned).strip()


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

    related_info = _strip_web_citations(data.get("related_info", "") or "")
    references = [
        {"title": _strip_web_citations(r.get("title", "")), "url": r.get("url", "")}
        for r in (data.get("references") or [])
        if r.get("url")
    ]

    # Safety net: backfill references from inline markdown links in related_info.
    # The agent is instructed to keep both in sync, but if it embeds [text](url)
    # without populating references, we extract them here so the right-side
    # references panel never misses a link shown in the related-info card.
    references = _merge_inline_links(related_info, references)

    return {
        "relatedInfo": related_info,
        "keywords": [
            str(k).strip()
            for k in (data.get("keywords") or [])
            if isinstance(k, (str, int, float)) and str(k).strip()
        ],
        "suggestedQuestions": [
            {"type": q.get("type", ""), "question": _strip_web_citations(q.get("question", "")), "rationale": _strip_web_citations(q.get("rationale", ""))}
            for q in data.get("suggested_questions", [])
        ],
        "references": references,
    }


# Markdown link pattern: [text](http(s)://...)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _merge_inline_links(related_info: str, references: list[dict]) -> list[dict]:
    """Merge inline markdown links from related_info into the references list.

    Ensures every URL that appears as a clickable link in the related-info
    text is also present in the references panel. Existing references take
    precedence (their title is preserved); newly discovered links are
    appended in document order. Duplicate URLs are removed.
    """
    if not related_info:
        return references

    seen_urls = {r["url"] for r in references if r.get("url")}
    merged = list(references)
    for match in _MARKDOWN_LINK_RE.finditer(related_info):
        text, url = match.group(1).strip(), match.group(2).strip()
        if url in seen_urls:
            continue
        merged.append({"title": text or url, "url": url})
        seen_urls.add(url)
    return merged
