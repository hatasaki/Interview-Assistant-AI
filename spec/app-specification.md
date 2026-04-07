# Interview Assistant AI — アプリケーション仕様書

## 1. 概要

Interview Assistant AI は、ブラウザベースのインタビュー補助Webアプリケーションである。  
**エキスパート（Interviewee）の暗黙知を素人（Interviewer）が効果的に引き出すこと**を最重要目的とし、リアルタイム文字起こし・AI エージェントによる関連情報提示・次の質問案提示を通じて Interviewer をサポートする。

### 1.1 主要コンセプト

- Interviewee はある技術領域に深い知識と経験を持つエキスパート
- Interviewer はその領域の素人
- AI エージェントが会話をリアルタイムに分析し、素人にわかるように関連情報と質問案を提示
- 提示する情報・質問案は専門用語を噛み砕いた平易な表現とする

---

## 2. システムアーキテクチャ

```
┌──────────────────────────────────────────────────────────────┐
│                    Browser (Frontend)                        │
│                     JavaScript / HTML                        │
│                                                              │
│  ┌──────────────┐  WebSocket    ┌──────────────────────────┐ │
│  │ Microphone   │──────────────▶│ Voice Live API           │ │
│  │ (getUserMedia │  audio in    │ wss://<resource>.services │ │
│  │  + Web Audio) │              │  .ai.azure.com/          │ │
│  └──────────────┘              │  voice-live/realtime     │ │
│                                │                          │ │
│                                │ onInputAudioTranscription│ │
│                                │ Completed (text events)  │ │
│                                └────────┬─────────────────┘ │
│                                         │ transcription      │
│                                         ▼ text               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │            Frontend Application                       │   │
│  │  左ペイン | 中央ペイン | 右ペイン                      │   │
│  └──────────────────────┬───────────────────────────────┘   │
│                          │ WebSocket                         │
└──────────────────────────┼───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              Backend (Python / App Service)                   │
│                                                              │
│  ┌────────────────────┐    ┌──────────────────────────────┐  │
│  │ WebSocket Server   │    │ Foundry Agent Service        │  │
│  │ (FastAPI)          │───▶│ (azure-ai-projects >= 2.0.0) │  │
│  └─────────┬──────────┘    │                              │  │
│            │               │  ┌────────────────────────┐  │  │
│            │ token API     │  │ MCP Tool:              │  │  │
│            │               │  │ Microsoft Learn        │  │  │
│            ▼               │  │ MCP Server             │  │  │
│  ┌────────────────────┐    │  │ learn.microsoft.com    │  │  │
│  │ Token Endpoint     │    │  │ /api/mcp               │  │  │
│  │ GET /api/voicelive │    │  └────────────────────────┘  │  │
│  │ /token             │    └──────────────────────────────┘  │
│  │ (Entra ID Bearer)  │                                      │
│  └────────────────────┘                                      │
│                                                              │
│  ┌────────────────────┐                                      │
│  │ Cosmos DB Client   │                                      │
│  │ (Managed Identity) │                                      │
│  └────────────────────┘                                      │
└──────────────────────────────────────────────────────────────┘
```

> **重要なアーキテクチャ上の決定事項:**
> - Voice Live API は本来 speech-to-speech（音声入出力双方向）用のAPIだが、本アプリでは **文字起こし専用** として利用する
> - `modalities: ["text"]` + `turn_detection.create_response: false` を設定し、モデルの自動応答を抑制
> - `input_audio_transcription` を明示的に設定し、入力音声の文字起こしイベント（`conversation.item.input_audio_transcription.completed`）を有効化
> - `azure_semantic_vad_multilingual` を使用（日本語対応。`azure_semantic_vad` は主に英語のみ）
> - ブラウザから Voice Live API に直接 WebSocket 接続するが、認証トークンはバックエンドから取得（`AzureKeyCredential` 経由）

### 2.1 技術スタック

| レイヤー | 技術 | 備考 |
|---|---|---|
| フロントエンド | JavaScript (Vanilla JS or lightweight framework) | モダン UI デザイン |
| バックエンド | Python (FastAPI) | App Service 上で稼働 |
| リアルタイム文字起こし | Azure Voice Live API | `@azure/ai-voicelive` JS SDK v1.0.0-beta.3（ブラウザ対応）|
| AI エージェント | Microsoft Foundry Agent Service（Prompt Agent） | `azure-ai-projects` >= 2.0.0 Python SDK |
| エージェントツール | Microsoft Learn MCP Server | エンドポイント: `https://learn.microsoft.com/api/mcp`（認証不要）|
| データストア | Azure Cosmos DB for NoSQL | Managed Identity 認証（`azure-cosmos`）|
| ホスティング | Azure App Service | Basic 認証無効（OIDC デプロイ） |
| ユーザー認証 | App Service Easy Auth (Microsoft Entra ID) | `azd up` 時に自動構成 |
| リソース間認証 | DefaultAzureCredential / ManagedIdentityCredential | 組織ポリシー準拠 |
| Voice Live 認証 | Entra ID Bearer Token（バックエンド発行 → フロントエンド利用）| `Cognitive Services User` ロール必要 |

### 2.2 Azureリソース

| リソース | 用途 |
|---|---|
| App Service | フロントエンド静的ファイル配信 + Python バックエンド |
| Microsoft Foundry リソース | Voice Live API エンドポイント + Foundry Agent Service（Prompt Agent）|
| Foundry プロジェクト | エージェント管理。エンドポイント形式: `https://<resource>.ai.azure.com/api/projects/<project>` |
| Cosmos DB for NoSQL | インタビューデータ永続化 |
| Entra ID App Registration | App Service Easy Auth 用アプリ登録（`azd up` で自動作成） |

---

## 3. 画面設計

### 3.1 全体レイアウト

```
┌──────────────────────────────────────────────────────────────────┐
│  Interview Assistant AI                                          │
├────────────────┬──────────────────────────────┬──────────────────┤
│                │                              │                  │
│   左ペイン      │       中央ペイン              │   右ペイン        │
│   (250px)      │       (flex: 1)              │   (300px)        │
│                │                              │                  │
│ ┌────────────┐ │ ┌──────────────────────────┐ │ ┌──────────────┐ │
│ │ 開始 │ 終了 │ │ │ Interviewee 情報表示     │ │ │ 参照元リンク  │ │
│ └────────────┘ │ │ (名前・所属)             │ │ │              │ │
│                │ └──────────────────────────┘ │ │ - MS Learn   │ │
│ ┌────────────┐ │                              │ │   Doc Link 1 │ │
│ │ 文字起こし  │ │ ┌──────────────────────────┐ │ │ - MS Learn   │ │
│ │ 表示エリア  │ │ │                          │ │ │   Doc Link 2 │ │
│ │            │ │ │  AI 提示エリア            │ │ │ - ...        │ │
│ │ (リアルタイ │ │ │  - 関連情報              │ │ │              │ │
│ │  ムスクロー │ │ │  - 次の質問案            │ │ │              │ │
│ │  ル)       │ │ │  - 背景情報              │ │ │              │ │
│ │            │ │ │                          │ │ │              │ │
│ │            │ │ └──────────────────────────┘ │ │              │ │
│ │            │ │                              │ │              │ │
│ │            │ │ ┌──────────────────────────┐ │ │              │ │
│ │            │ │ │ AI チャットボックス       │ │ │              │ │
│ │            │ │ │ [質問を入力...    ] 送信  │ │ │              │ │
│ └────────────┘ │ └──────────────────────────┘ │ └──────────────┘ │
│                │                              │                  │
│ ┌────────────┐ │                              │                  │
│ │レポート表示 │ │                              │                  │
│ │ボタン      │ │                              │                  │
│ └────────────┘ │                              │                  │
├────────────────┴──────────────────────────────┴──────────────────┤
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 UI コンポーネント詳細

#### ヘッダー
- 左上に「**Interview Assistant AI**」のアプリタイトル
- モダンなフォント・スタイリング

#### 左ペイン（トランスクリプション・操作パネル）
| 要素 | 説明 |
|---|---|
| 開始ボタン | インタビュー詳細登録後にクリック可能になる。クリックで文字起こし開始 |
| 終了ボタン | インタビュー中に表示。クリックでインタビュー終了・レポート生成開始 |
| 文字起こし表示エリア | リアルタイムに会話内容がスクロール表示される |
| レポート表示ボタン | インタビュー終了後、レポート生成完了時にクリック可能になる |

#### 中央ペイン（メインコンテンツ）
| 要素 | 説明 |
|---|---|
| インタビュー詳細登録ボタン | アプリ起動時に中央ペイン上部に表示。モーダルを開く |
| Interviewee 情報表示 | 登録後に名前・所属を表示 |
| AI 提示エリア | エージェントが生成した関連情報・次の質問案・背景情報を表示 |
| AI チャットボックス | Interviewer がエージェントに補足質問を入力するテキスト入力 + 送信ボタン |

#### 右ペイン（参照元パネル）
| 要素 | 説明 |
|---|---|
| 参照元リンクリスト | エージェントが参照した Microsoft Learn ドキュメント等へのリンクを表示 |

### 3.3 モーダル：インタビュー詳細登録

アプリ起動後、中央ペイン上部の「インタビュー詳細登録」ボタンをクリックすると表示される。

| フィールド | 入力タイプ | 必須 | 説明 |
|---|---|---|---|
| インタビュー対象者の名前 | テキスト | ○ | Interviewee の氏名 |
| 所属 | テキスト | ○ | Interviewee の所属組織・部署 |
| 関連情報 | テキストエリア（大） | △ | Interviewee の専門領域・背景情報・事前情報など |
| インタビュー時間 | 数値（分） | ○ | 予定インタビュー時間 |
| ゴール | テキストエリア | ○ | インタビューで達成したい目標・聞き出したい内容 |

- 「登録」ボタンで保存しモーダルを閉じる
- 登録後、左ペインの「開始」ボタンがクリック可能になる

---

## 4. 機能仕様

### 4.1 インタビューフロー

```
アプリ起動
    │
    ▼
[中央ペイン] インタビュー詳細登録ボタン表示
    │ クリック
    ▼
[モーダル] インタビュー詳細入力
    │ 登録
    ▼
[左ペイン] 「開始」ボタンがアクティブ化
    │ クリック
    ▼
文字起こし開始（Voice Live API 接続）
    │
    ├──▶ [左ペイン] リアルタイム文字起こし表示開始
    │
    ├──▶ [中央ペイン] 最初の声掛け内容案を表示
    │
    ├──▶ エージェントへインタビュー情報送信
    │
    ▼
インタビュー進行中（リアルタイムループ）
    │
    ├──▶ 文字起こしテキスト → エージェントへ送信
    │
    ├──▶ エージェント → 関連情報 + 次の質問案を中央ペインに表示
    │
    ├──▶ エージェント → 参照元リンクを右ペインに表示
    │
    ├──▶ Interviewer → AI チャットボックスで補足質問（任意）
    │
    ▼
[左ペイン] 「終了」ボタン クリック
    │
    ▼
文字起こし停止
    │
    ▼
レポート生成エージェント起動
    │ （会話履歴 + エージェント提示内容 → レポート化）
    │
    ▼
[左ペイン] 「レポート表示」ボタンがクリック可能
    │ クリック
    ▼
レポート表示（マークダウン形式）
```

### 4.2 リアルタイム文字起こし

- **技術**: Azure Voice Live API（`@azure/ai-voicelive` JavaScript SDK v1.0.0-beta.3）
- **接続方式**: ブラウザから直接 Voice Live API に WebSocket 接続
  - WebSocket エンドポイント: `wss://<resource>.services.ai.azure.com/voice-live/realtime?api-version=2025-10-01&model=<model>`
- **音声入力**: Interviewer の PC マイク（`navigator.mediaDevices.getUserMedia()` で取得）
- **文字起こしイベント**: `onInputAudioTranscriptionCompleted` でテキスト取得
- **セッション設定（文字起こし専用モード）**:
  - `modalities`: `["text"]`（モデルの音声出力を無効化）
  - `inputAudioFormat`: `"pcm16"`
  - `inputAudioTranscription`: `{ model: "azure-speech", language: "ja" }`（Azure STT で入力音声を文字起こし）
  - `turnDetection`: `{ type: "azure_semantic_vad_multilingual", create_response: false, silence_duration_ms: 500, languages: ["ja"] }`
    - `create_response: false` を設定し、モデルの自動応答を抑制（文字起こしのみ取得）
    - `azure_semantic_vad_multilingual` で日本語対応の高精度な発話区間検出（日本語を含む多言語対応。`azure_semantic_vad` は主に英語のみ）
- **話者識別**: Voice Live API は話者識別（ダイアライゼーション）を提供しないため、エージェントが文脈から推測する
- **文字起こしテキストの流れ**:
  1. ブラウザが Voice Live API に PCM16 音声データを `session.sendAudio()` で送信
  2. Voice Live API が `onInputAudioTranscriptionCompleted` イベントで文字起こしテキストを返送
  3. 左ペインにリアルタイム表示
  4. WebSocket 経由でバックエンドに送信
  5. バックエンドが Cosmos DB に保存 + Foundry Agent Service に入力
- **ブラウザ認証**:
  - `DefaultAzureCredential` はブラウザでは使用不可
  - バックエンド API `GET /api/voicelive/token` で Microsoft Entra ID トークン（scope: `https://ai.azure.com/.default` 推奨。レガシー: `https://cognitiveservices.azure.com/.default`）を取得
  - フロントエンドは取得したトークンを `AzureKeyCredential` 経由で Voice Live SDK に渡す（SDK が内部的に `api-key` クエリパラメータとして WebSocket 接続時に使用）
  - **注意**: `AzureKeyCredential` は API キー認証用だが、Entra ID トークンも同じインターフェースで渡すことが可能。SDK が適切にハンドリングする
  - トークンは短時間で失効するため、セッション中に定期的に再取得する

### 4.3 インタビュー補助エージェント

#### エージェント構成

- **サービス**: Microsoft Foundry Agent Service
- **SDK**: `azure-ai-projects` >= 2.0.0 (Python, Foundry projects new API)
  - 注意: v1.x とは互換性がない。必ず v2.x を使用すること
- **モデル**: GPT-4o 以上推奨（`gpt-4o` / `gpt-4.1` / `gpt-5` / `gpt-5-mini` 等）
- **エンドポイント形式**: `https://<AIFoundryResourceName>.ai.azure.com/api/projects/<ProjectName>`
- **ツール**: Microsoft Learn MCP Server
  - `server_label`: `"microsoft_learn"`
  - `server_url`: `"https://learn.microsoft.com/api/mcp"`
  - `require_approval`: `"never"`（リアルタイム性重視のため自動承認）
  - 利用可能ツール: `microsoft_docs_search`, `microsoft_code_sample_search`, `microsoft_docs_fetch`

#### エージェントのシステムプロンプト（概要）

```
あなたはインタビュー補助 AI エージェントです。

## 役割
- エキスパート（Interviewee）の暗黙知を引き出すため、素人（Interviewer）をサポートする
- Microsoft Learn MCP Server を使って関連情報を検索し、Interviewer に提示する
- Interviewer が次に聞くべき質問案を、背景情報とともに提示する

## 制約
- 提示する情報はすべて素人にわかりやすい平易な表現で記述する
- 専門用語を使う場合は必ず簡潔な説明を付ける
- 文字起こしは Interviewer と Interviewee の区別がない場合がある。文脈から推測すること
- インタビューの時間とゴールを常に意識し、ゴール達成に向けた質問を優先する

## 入力情報
- Interviewee の名前・所属・関連情報
- インタビュー時間・ゴール
- リアルタイムの文字起こし内容

## 出力形式
以下を JSON 形式で返す:
{
  "related_info": "関連情報の平易な説明",
  "suggested_questions": [
    {
      "question": "次に聞くべき質問",
      "rationale": "なぜこの質問が重要か（素人向け説明）"
    }
  ],
  "references": [
    {
      "title": "参照元ドキュメントタイトル",
      "url": "https://learn.microsoft.com/..."
    }
  ]
}
```

#### エージェント呼び出しフロー

```python
# Foundry Agent Service クライアント初期化
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition, MCPTool

project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)
openai = project.get_openai_client()

# --- エージェントの事前作成（初回セットアップ時のみ） ---
mcp_tool = MCPTool(
    server_label="microsoft_learn",
    server_url="https://learn.microsoft.com/api/mcp",
    require_approval="never",
)

agent = project.agents.create_version(
    agent_name="interview-assistant",
    definition=PromptAgentDefinition(
        model="gpt-4o",
        instructions=SYSTEM_PROMPT,
        tools=[mcp_tool],
    ),
)

# --- アプリ起動時（既存エージェントを取得） ---
agent = project.agents.get("interview-assistant")

# --- インタビューセッションごとに新しい会話を作成 ---
conversation = openai.conversations.create()
response = openai.responses.create(
    conversation=conversation.id,
    input=user_message,
    extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
)
```

### 4.4 Interviewer → AI チャット Q&A

- 中央ペイン下部のチャットボックスで Interviewer がエージェントに直接質問可能
- 毎回新規の conversation を作成し、インタビュー詳細情報 + 直近の文字起こし履歴（5000文字）+ 質問内容をプロンプトに含めて送信
- エージェントは質問への**回答と関連する参照情報のみ**を返す（質問案は返さない）
- 応答は中央ペインに「チャット」タイトル付きのカードとして表示
- 参照情報のリンクは右ペインにも追加される

### 4.5 最終レポート生成

- インタビュー終了時に、レポート生成用エージェント（または同一エージェントへの特別プロンプト）を使用
- **入力**: Cosmos DB から全会話履歴 + エージェント提示内容 + インタビュー詳細情報を取得
- **出力**: マークダウン形式のレポート
- **処理方式**: 非同期実行（FastAPI の `BackgroundTasks` または別プロセス）
- レポート生成完了後、WebSocket で `report_ready` を送信し、左ペインの「レポート表示」ボタンがクリック可能
- レポートは Cosmos DB に保存
- 生成状況は `GET /api/interviews/{id}/report/status` でも確認可能

#### レポート構成（案）

```markdown
# インタビューレポート

## 基本情報
- 対象者: {名前} ({所属})
- 実施日時: {日時}
- インタビュー時間: {実績時間}
- インタビューゴール: {ゴール}

## エグゼクティブサマリー
{インタビュー全体の要約}

## 主要な知見
### 知見 1: {タイトル}
{詳細説明}

### 知見 2: {タイトル}
{詳細説明}

## 会話ハイライト
{重要な会話のポイント}

## 参照情報
- [ドキュメントタイトル](URL)

## 今後のアクション・推奨事項
{推奨事項}
```

---

## 5. データモデル（Cosmos DB）

### 5.1 コンテナ設計

**データベース名**: `interview-assistant-db`

> **設計判断**: Cosmos DB では同一パーティションキーで型が異なるドキュメントを1コンテナに格納する「単一コンテナ + type 識別」パターンも有力だが、本アプリではクエリパターンの明確さと開発効率を優先して**コンテナ分割方式**を採用する。将来的にスケーラビリティの問題が発生した場合はコンテナ統合を検討する。

#### コンテナ: `interviews`

パーティションキー: `/interviewId`

```json
{
  "id": "uuid",
  "interviewId": "uuid",
  "type": "interview_metadata",
  "intervieweeName": "対象者名",
  "intervieweeAffiliation": "所属",
  "relatedInfo": "関連情報テキスト",
  "durationMinutes": 60,
  "goal": "インタビューゴール",
  "status": "not_started | in_progress | completed",
  "startedAt": "ISO 8601 datetime",
  "endedAt": "ISO 8601 datetime",
  "createdAt": "ISO 8601 datetime",
  "updatedAt": "ISO 8601 datetime"
}
```

#### コンテナ: `transcripts`

パーティションキー: `/interviewId`

```json
{
  "id": "uuid",
  "interviewId": "uuid",
  "type": "transcript_entry",
  "text": "文字起こしテキスト",
  "timestamp": "ISO 8601 datetime",
  "sequenceNumber": 1
}
```

#### コンテナ: `agent_responses`

パーティションキー: `/interviewId`

```json
{
  "id": "uuid",
  "interviewId": "uuid",
  "type": "agent_response",
  "relatedInfo": "関連情報",
  "suggestedQuestions": [
    {
      "question": "質問文",
      "rationale": "理由"
    }
  ],
  "references": [
    {
      "title": "タイトル",
      "url": "URL"
    }
  ],
  "timestamp": "ISO 8601 datetime",
  "triggerTranscriptId": "関連するtranscript entry ID"
}
```

#### コンテナ: `chat_messages`

パーティションキー: `/interviewId`

```json
{
  "id": "uuid",
  "interviewId": "uuid",
  "type": "chat_message",
  "role": "interviewer | agent",
  "content": "メッセージ内容",
  "timestamp": "ISO 8601 datetime"
}
```

#### コンテナ: `reports`

パーティションキー: `/interviewId`

```json
{
  "id": "uuid",
  "interviewId": "uuid",
  "type": "report",
  "markdownContent": "レポートのマークダウンテキスト",
  "status": "generating | completed | failed",
  "createdAt": "ISO 8601 datetime",
  "completedAt": "ISO 8601 datetime"
}
```

### 5.2 Cosmos DB 接続

- **認証**: Managed Identity（`DefaultAzureCredential`）
  - 接続文字列・アクセスキーは使用禁止（組織ポリシー）
- **SDK**: `azure-cosmos` (Python)
- **一貫性レベル**: Session（同一セッション内の読み取り一貫性確保）

---

## 6. API 設計（Backend）

### 6.1 REST API

| メソッド | パス | 説明 |
|---|---|---|
| POST | `/api/interviews` | インタビュー詳細を登録 |
| GET | `/api/interviews/{id}` | インタビュー詳細を取得 |
| POST | `/api/interviews/{id}/start` | インタビュー開始（エージェント初期化） |
| POST | `/api/interviews/{id}/stop` | インタビュー終了（レポート生成開始） |
| GET | `/api/interviews/{id}/report` | 生成済みレポートを取得 |
| GET | `/api/interviews/{id}/report/status` | レポート生成状況を取得 |
| GET | `/api/voicelive/token` | Voice Live API 用 Entra ID トークン発行 |

### 6.2 WebSocket API

| エンドポイント | 方向 | メッセージ型 | 説明 |
|---|---|---|---|
| `/ws/interview/{id}` | Client → Server | `transcript` | 文字起こしテキスト送信（DB保存のみ） |
| `/ws/interview/{id}` | Client → Server | `supplementary_info` | 無音検出後バッファテキスト送信 → 補足情報生成 |
| `/ws/interview/{id}` | Client → Server | `generate_questions` | 「次の質問を生成」ボタン → 質問案生成 |
| `/ws/interview/{id}` | Client → Server | `chat_message` | Interviewer のチャット質問 → 回答+参照情報（質問案なし） |
| `/ws/interview/{id}` | Server → Client | `agent_suggestion` | エージェントの関連情報・質問案（cardTitle付き） |
| `/ws/interview/{id}` | Server → Client | `agent_references` | 参照元リンク情報 |
| `/ws/interview/{id}` | Server → Client | `report_ready` | レポート生成完了通知 |

#### WebSocket メッセージ形式

```json
// Client → Server: 文字起こし
{
  "type": "transcript",
  "text": "文字起こしされたテキスト",
  "timestamp": "ISO 8601"
}

// Client → Server: 補足質問
{
  "type": "chat_message",
  "content": "エージェントへの質問"
}

// Server → Client: エージェント提案
{
  "type": "agent_suggestion",
  "relatedInfo": "関連情報テキスト（素人にわかりやすく）",
  "suggestedQuestions": [
    {
      "question": "次の質問案",
      "rationale": "この質問の背景・重要性"
    }
  ]
}

// Server → Client: 参照元
{
  "type": "agent_references",
  "references": [
    {
      "title": "Microsoft Learn ドキュメント名",
      "url": "https://learn.microsoft.com/..."
    }
  ]
}

// Server → Client: レポート完了
{
  "type": "report_ready",
  "reportId": "uuid"
}
```

---

## 7. プロジェクト構成

```
interview-assistant-ai/
├── .github/
│   ├── copilot-instructions.md
│   ├── instructions/
│   │   ├── azure-deploy.instructions.md
│   │   └── azure-infra.instructions.md
│   └── workflows/
│       └── deploy.yml                 # GitHub Actions OIDC デプロイ
├── spec/
│   └── app-specification.md           # 本ファイル
├── frontend/
│   ├── index.html                     # SPA エントリーポイント
│   ├── css/
│   │   └── style.css                  # モダン UI スタイル
│   ├── js/
│   │   ├── app.js                     # アプリメイン
│   │   ├── voicelive.js               # Voice Live API 直接 WebSocket 接続
│   │   ├── websocket.js               # バックエンド WebSocket 通信 + 無音検出
│   │   ├── ui.js                      # UI 操作・レンダリング
│   │   └── modal.js                   # インタビュー詳細登録モーダル
│   ├── public/
│   │   └── js/
│   │       └── pcm-processor.js       # AudioWorklet PCM16 変換プロセッサ
│   ├── package.json                   # npm 依存定義（SDK不使用）
│   ├── vite.config.js                 # Vite バンドラー設定
│   └── dist/                          # ビルド成果物（.gitignore 対象）
├── backend/
│   ├── requirements.txt
│   ├── startup.sh                     # App Service 起動スクリプト
│   ├── app.py                         # FastAPI アプリエントリーポイント（スレッドプール拡張）
│   ├── config.py                      # 環境変数・設定
│   ├── routers/
│   │   ├── interviews.py              # REST API ルーター
│   │   ├── voicelive.py               # Voice Live トークン発行 API
│   │   └── websocket.py               # WebSocket ルーター（3つのエージェント役割）
│   ├── services/
│   │   ├── agent_service.py           # Foundry Agent Service 連携 + レポート生成
│   │   ├── cosmos_service.py          # Cosmos DB CRUD
│   │   └── report_service.py          # レポート生成（バックグラウンドタスク）
│   └── models/
│       └── schemas.py                 # Pydantic モデル
├── infra/
│   ├── main.bicep                     # Azure インフラ定義
│   ├── abbreviations.json             # リソース名略称
│   ├── main.parameters.json           # パラメータテンプレート
│   ├── scripts/
│   │   ├── auth-preprovision.ps1      # Entra ID App Registration 作成 (Windows)
│   │   ├── auth-preprovision.sh       # Entra ID App Registration 作成 (Linux/macOS)
│   │   ├── auth-postprovision.ps1     # リダイレクト URI 設定 (Windows)
│   │   └── auth-postprovision.sh      # リダイレクト URI 設定 (Linux/macOS)
│   └── modules/
│       ├── app-service.bicep          # App Service + Plan + Easy Auth (authsettingsV2)
│       ├── cosmos-db.bicep            # Cosmos DB + コンテナ
│       ├── cosmos-rbac.bicep          # Cosmos DB RBAC
│       ├── ai-foundry.bicep           # New Foundry (CognitiveServices/accounts + projects)
│       └── ai-rbac.bicep              # AI Foundry RBAC
├── azure.yaml                         # azd 構成（preprovision/postprovision/prepackage フック付き）
└── README.md
```

---

## 8. 依存パッケージ

### 8.1 Frontend (npm)

```json
{
  "dependencies": {}
}
```

> **重要な実装上の決定**: `@azure/ai-voicelive` SDK v1.0.0-beta.3 は `input_audio_transcription` プロパティのシリアライズに対応していないため、SDK を使用せず **Voice Live API に直接 WebSocket 接続**する方式を採用。フロントエンドに npm 依存パッケージはない（Vite のみ devDependencies）。

**フロントエンドのビルド**: Vite でバンドルし `frontend/dist/` に出力。`azd` の prepackage フックで自動実行。

### 8.2 Backend (pip)

```
fastapi>=0.110.0
uvicorn>=0.29.0
websockets>=12.0
azure-ai-projects>=2.0.0
azure-identity>=1.17.0
azure-cosmos>=4.7.0
pydantic>=2.0
```

---

## 9. 認証・セキュリティ

### 9.1 ユーザー認証（Easy Auth）

- **App Service Easy Auth（認証/承認）** を使用し、Microsoft Entra ID でユーザーを認証
- `azd up` の `preprovision` フックで Entra ID App Registration とクライアントシークレットを自動作成
- `postprovision` フックで App Service の URL に基づくリダイレクト URI を自動設定
- Bicep の `authsettingsV2` リソースで Easy Auth を構成:
  - 未認証リクエスト: ログインページへリダイレクト
  - トークンストア: 有効
  - Issuer URL: `https://login.microsoftonline.com/{tenantId}/v2.0`（v2.0 エンドポイント）
- クライアントシークレットは App Service のアプリ設定 `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` に格納
- 認証フロー: ハイブリッドフロー（`response_type=code id_token`）

### 9.2 Azure リソース間認証

- すべて **Managed Identity** を使用（組織ポリシー）
- `DefaultAzureCredential` によるフォールバック（ローカル開発時は Azure CLI 認証）
- アクセスキー・接続文字列によるキーベース認証は **禁止**

### 9.3 必要な RBAC ロール

| リソース | ロール | 対象 |
|---|---|---|
| AI Foundry プロジェクト | Azure AI User | App Service Managed Identity |
| Microsoft Foundry リソース | Cognitive Services User | App Service Managed Identity |
| Microsoft Foundry リソース | Azure AI User | App Service Managed Identity |
| Cosmos DB | Cosmos DB Built-in Data Contributor | App Service Managed Identity |

> **注意**: Voice Live API の認証には `Cognitive Services User` **と** `Azure AI User` の**両方**のロールが必要。

### 9.4 Voice Live トークン API のセキュリティ

- `GET /api/voicelive/token` エンドポイントは Easy Auth により認証済みユーザーのみアクセス可能
- トークンの有効期限を応答に含め、フロントエンドが期限前に再取得できるようにする

### 9.5 WebSocket 接続の認証

- `/ws/interview/{id}` WebSocket エンドポイントは Easy Auth のセッション Cookie により認証される
- 不正な接続は直ちに切断する

### 9.6 デプロイ

- GitHub Actions + OIDC（フェデレーション資格情報）を使用
- Basic 認証（SCM/FTP）は無効化（組織ポリシー）
- publish-profile シークレットは使用不可

---

## 10. Voice Live API 詳細仕様

### 10.1 ブラウザ認証フロー

Voice Live API は Microsoft Entra ID のBearerトークン認証を使用する。ブラウザでは `DefaultAzureCredential` が使用できないため、以下のフローを採用する:

```
Browser                          Backend                       Entra ID
  │                                │                              │
  │ GET /api/voicelive/token       │                              │
  │──────────────────────────────▶│                              │
  │                                │ DefaultAzureCredential       │
  │                                │  .get_token(scope)           │
  │                                │─────────────────────────────▶│
  │                                │◀─────────────────────────────│
  │                                │  Bearer token                │
  │◀──────────────────────────────│                              │
  │  { token, endpoint, model }    │                              │
  │                                │                              │
  │ WebSocket connect with Bearer  │                              │
  │────────────────────────────────────────▶ Voice Live API       │
```

**バックエンド側トークン発行（Python）:**

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()

@app.get("/api/voicelive/token")
async def get_voicelive_token():
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return {
        "token": token.token,
        "endpoint": VOICELIVE_ENDPOINT,  # e.g. "https://<resource>.services.ai.azure.com"
        "model": VOICELIVE_MODEL,        # e.g. "gpt-4o"
        "expiresOn": token.expires_on,
    }
```

### 10.2 ブラウザ側実装（直接 WebSocket 接続）

SDK を使用せず、Voice Live API に直接 WebSocket 接続する。認証は `authorization` クエリパラメータで Bearer トークンを送信する。

```javascript
// バックエンドからトークンを取得
const res = await fetch("/api/voicelive/token");
const { token, endpoint, model } = await res.json();

// WebSocket URL を構築（Bearer トークンを authorization パラメータで送信）
const host = new URL(endpoint).host;
const wsUrl = `wss://${host}/voice-live/realtime?api-version=2025-10-01&model=${model}&authorization=${encodeURIComponent("Bearer " + token)}`;
const ws = new WebSocket(wsUrl);

ws.onopen = () => {
  // session.update で文字起こし専用モードを設定
  ws.send(JSON.stringify({
    type: "session.update",
    session: {
      modalities: ["text"],
      input_audio_format: "pcm16",
      input_audio_transcription: { model: "azure-speech", language: "ja" },
      turn_detection: {
        type: "azure_semantic_vad_multilingual",
        create_response: false,
        silence_duration_ms: 500,
        languages: ["ja"],
      },
      input_audio_noise_reduction: { type: "azure_deep_noise_suppression" },
    },
  }));
};

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "session.updated") startMicrophoneCapture();
  if (msg.type === "conversation.item.input_audio_transcription.completed") {
    displayTranscript(msg.transcript);
    sendToBackend(msg.transcript);
  }
};

// 音声は input_audio_buffer.append で base64 エンコードして送信
ws.send(JSON.stringify({ type: "input_audio_buffer.append", audio: base64Data }));
```

> **SDK 不使用の理由**: `@azure/ai-voicelive` v1.0.0-beta.3 の `requestSessionSerializer` が `input_audio_transcription` プロパティをシリアライズ対象に含めていないため、SDK 経由では文字起こしイベントが発火しない。直接 WebSocket 接続により REST API プロトコルの snake_case プロパティ名をそのまま送信することで解決。

### 10.3 Voice Live API セッション設定の詳細

| パラメータ | 値 | 理由 |
|---|---|---|
| `modalities` | `["text"]` | 音声出力不要（テキスト文字起こしのみ）|
| `input_audio_transcription.model` | `"azure-speech"` | Azure STT による高精度文字起こし |
| `input_audio_transcription.language` | `"ja"` | 日本語インタビュー向け |
| `turn_detection.type` | `"azure_semantic_vad_multilingual"` | 多言語対応セマンティック VAD（日本語含む10言語対応）|
| `turn_detection.create_response` | `false` | **重要**: モデルの自動応答を抑制し、文字起こしのみ取得 |
| `turn_detection.silence_duration_ms` | `500` | 発話終了判定の無音時間 |
| `turn_detection.languages` | `["ja"]` | 日本語でのフィラーワード除去精度向上 |
| `input_audio_noise_reduction.type` | `"azure_deep_noise_suppression"` | 環境ノイズ除去 |
| `input_audio_format` | `"pcm16"` | 標準 PCM 16bit フォーマット |
| `input_audio_sampling_rate` | `24000` | デフォルトサンプリングレート |

> **設計判断の根拠**: Voice Live API は本来 speech-to-speech 用だが、`create_response: false` と `modalities: ["text"]` の組み合わせにより、文字起こし専用モードとして機能させる。Voice Live API を採用する利点は、Azure Semantic VAD による高精度な発話区間検出、ノイズ抑制、および WebSocket ベースの低遅延リアルタイム処理である。
> 
> **`azure_semantic_vad` vs `azure_semantic_vad_multilingual`**: `azure_semantic_vad` は主に英語のみサポート。日本語インタビューでは **`azure_semantic_vad_multilingual`** を使用すること（日本語・英語・中国語・韓国語等10言語対応）。

### 10.4 Voice Live API サポートモデル（文字起こし用）

| モデル | 説明 | 推奨度 |
|---|---|---|
| `gpt-4o` | GPT-4o + Azure STT 入力 | ○ 推奨（コスト・品質バランス）|
| `gpt-4o-mini` | GPT-4o mini + Azure STT 入力 | ◎ 最推奨（文字起こし専用なら低コスト）|
| `gpt-4.1-mini` | GPT-4.1 mini + Azure STT 入力 | ○ 推奨 |
| `gpt-5-nano` | GPT-5 nano + Azure STT 入力 | ○ 最低コスト |

> 注: `create_response: false` 設定により、モデルの推論は実質発生しないため、STT 処理のみのコストとなる。低コストモデルの選択を推奨。

---

## 11. 非機能要件

| 項目 | 要件 |
|---|---|
| レイテンシ | 文字起こし: 1秒以内の遅延。エージェント応答: 5秒以内目標 |
| 同時接続 | 要確認（質問事項参照） |
| UI | モダンデザイン、レスポンシブ、ダークモード非対応でも可 |
| ブラウザ対応 | Chrome, Edge（最新版）。Safari は AudioWorklet API の互換性要確認 |
| データ保持 | 要確認（質問事項参照） |

### 11.1 エラーハンドリング・リカバリ

| シナリオ | 対応方針 |
|---|---|
| Voice Live WebSocket 切断 | 自動再接続（exponential backoff）。再接続時にトークンを再取得 |
| バックエンド WebSocket 切断 | 自動再接続。文字起こしはフロントエンド側でバッファリングし、再接続後に送信 |
| Foundry Agent Service タイムアウト | リトライ（最大3回）。失敗時は UI にエラー表示 |
| MCP ツール呼び出し失敗 | エージェントが別の検索クエリで再試行。最終的に失敗時はユーザーに通知 |
| Cosmos DB 書き込み失敗 | リトライ（冪等性を確保）。文字起こしデータはメモリバッファに保持 |
| トークン失効 | セッション中に定期的に更新（失効60秒前に再取得） |
| マイクアクセス拒否 | ユーザーに権限要求のガイダンスを表示 |

### 11.2 エージェントライフサイクル管理

- エージェントは Foundry プロジェクト内で**事前に作成・設定**しておく方式を推奨
- アプリ起動時に `project.agents.get(agent_name)` で既存エージェントを取得
- インタビューセッションごとに `openai.conversations.create()` で新しい会話を作成
- エージェント自体はセッション間で共有される永続リソース
- レポート生成時は**同一エージェント・別会話**で実行するか、レポート専用エージェントを別途用意

### 11.3 レポート生成の非同期処理

- レポート生成は長時間かかる可能性があるため、非同期で実行
- `POST /api/interviews/{id}/stop` でバックグラウンドタスクとして開始
- フロントエンドは WebSocket の `report_ready` メッセージ、または `GET /api/interviews/{id}/report/status` のポーリングで完了を検知

---

## 12. 技術参考リンク

| 技術 | ドキュメント |
|---|---|
| Voice Live API 概要 | https://learn.microsoft.com/azure/ai-services/speech-service/voice-live |
| Voice Live JS SDK (npm) | https://www.npmjs.com/package/@azure/ai-voicelive |
| Voice Live JS SDK リファレンス | https://learn.microsoft.com/javascript/api/overview/azure/ai-voicelive-readme?view=azure-node-preview |
| Voice Live API リファレンス (2025-10-01) | https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-api-reference-2025-10-01 |
| Voice Live How-to ガイド | https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-how-to |
| Voice Live クイックスタート (JS) | https://learn.microsoft.com/azure/ai-services/speech-service/voice-live-quickstart?pivots=programming-language-javascript |
| Foundry Agent Service 概要 | https://learn.microsoft.com/azure/foundry/agents/overview |
| Foundry クイックスタート (Python) | https://learn.microsoft.com/azure/foundry/quickstarts/get-started-code?pivots=programming-language-python |
| Foundry Agent + MCP ツール | https://learn.microsoft.com/azure/foundry/agents/how-to/tools/model-context-protocol |
| Microsoft Learn MCP Server 利用開始 | https://learn.microsoft.com/training/support/mcp-get-started-foundry |
| azure-ai-projects PyPI (>= 2.0.0) | https://pypi.org/project/azure-ai-projects/ |
| App Service + Foundry Agent チュートリアル | https://learn.microsoft.com/azure/app-service/tutorial-ai-agent-web-app-langgraph-foundry-python |
| Cosmos DB Python SDK (Managed Identity) | https://learn.microsoft.com/azure/cosmos-db/how-to-python-get-started |
| Cosmos DB RBAC 認証 | https://learn.microsoft.com/azure/cosmos-db/how-to-connect-role-based-access-control |

---

## 13. 調査結果に基づく補足事項

### 13.1 Foundry Agent Service SDK バージョン

- **Azure AI Projects 2.x**（`azure-ai-projects >= 2.0.0`）を使用すること
- 2.x は Foundry projects (new) API に対応し、1.x（Foundry classic）とは互換性がない
- 主要な API パターン:
  - `AIProjectClient(endpoint, credential)` でプロジェクトクライアント作成
  - `project.get_openai_client()` で OpenAI クライアント取得
  - `project.agents.create_version()` でエージェント作成
  - `openai.conversations.create()` で会話作成
  - `openai.responses.create(conversation=..., input=..., extra_body={"agent_reference": ...})` でエージェント呼び出し

### 13.2 Voice Live API の文字起こし専用利用について

- Voice Live API は本質的に speech-to-speech API であり、文字起こし専用の API ではない
- `turn_detection.create_response = false` で自動応答を抑制し、`input_audio_transcription` で文字起こしのみ取得する運用
- `onInputAudioTranscriptionCompleted` イベントは入力音声の文字起こし結果を提供する（モデル応答とは独立）
- 代替案として Azure AI Speech Transcription SDK（`@azure/ai-speech-transcription`）も存在するが、ユーザー要件により Voice Live API を採用

### 13.3 Microsoft Learn MCP Server

- エンドポイント: `https://learn.microsoft.com/api/mcp`
- 認証: 不要（Unauthenticated）
- 利用可能ツール: `microsoft_docs_search`, `microsoft_code_sample_search`, `microsoft_docs_fetch`
- Foundry Agent Service の `MCPTool` で接続し、`require_approval="never"` で自動承認

### 13.4 Cosmos DB Managed Identity 認証

- `azure-cosmos` パッケージの `CosmosClient` に `DefaultAzureCredential` を直接渡す
- RBAC ロール `Cosmos DB Built-in Data Contributor` を App Service の Managed Identity に付与
- アクセスキー・接続文字列は使用禁止（組織ポリシー）

---
