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
│  ┌──────────────┐              ┌──────────────────────────┐ │
│  │ Microphone   │              │ Azure Speech SDK         │ │
│  │ (getUserMedia │─────────────▶│ (CDN: microsoft.         │ │
│  │  via SDK)    │              │  cognitiveservices.       │ │
│  └──────────────┘              │  speech.sdk.bundle.js)   │ │
│                                │                          │ │
│                                │ ConversationTranscriber  │ │
│                                │ .transcribed             │ │
│                                │  (text + speakerId)      │ │
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
│  │ GET /api/speech    │    │  └────────────────────────┘  │  │
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
> - リアルタイム文字起こしには **Azure AI Speech SDK**（`microsoft-cognitiveservices-speech-sdk` CDN版）の連続会話文字起こし（`ConversationTranscriber.startTranscribingAsync`）を使用し、話者分離により `speakerId`（例: `Guest-1`, `Guest-2`, `Unknown`）を取得する
> - Speech SDK はブラウザで直接マイク入力をハンドリングし、Azure Speech Service のWebSocketエンドポイントに接続する
> - AI Foundry リソース（`kind: AIServices`）が提供する `cognitiveservices.azure.com` ドメインのエンドポイントを使用
> - Entra ID 認証は `SpeechConfig.fromEndpoint(URL, TokenCredential)` でトークンクレデンシャルを渡す方式
> - ノイズ抑制は Speech SDK の Microsoft Audio Stack（MAS）がJavaScriptで利用不可のため、ブラウザの WebRTC ノイズ抑制（`getUserMedia` デフォルト有効）に依存する

### 2.1 技術スタック

| レイヤー | 技術 | 備考 |
|---|---|---|
| フロントエンド | JavaScript (Vanilla JS) + Vite | モダン UI デザイン |
| バックエンド | Python (FastAPI) | App Service 上で稼働 |
| リアルタイム文字起こし | Azure AI Speech SDK | `microsoft-cognitiveservices-speech-sdk` CDN版（ブラウザ連続会話文字起こし・話者分離対応）|
| AI エージェント | Microsoft Foundry Agent Service（Prompt Agent） | `azure-ai-projects` >= 2.0.0 Python SDK |
| エージェントツール | Microsoft Learn MCP Server | エンドポイント: `https://learn.microsoft.com/api/mcp`（認証不要）|
| データストア | Azure Cosmos DB for NoSQL | Managed Identity 認証（`azure-cosmos`）|
| Embedding | text-embedding-3-small | AI Foundry 経由でベクトル化 |
| MCP Server | Azure Functions (Flex Consumption) | Cosmos DB ベクトル検索ツール提供 |
| ホスティング | Azure App Service | Basic 認証無効（OIDC デプロイ） |
| ユーザー認証 | App Service Easy Auth (Microsoft Entra ID) | `azd up` 時に自動構成 |
| リソース間認証 | DefaultAzureCredential / ManagedIdentityCredential | 組織ポリシー準拠 |
| Speech 認証 | Entra ID Bearer Token（バックエンド発行 → フロントエンド利用）| `Cognitive Services User` ロール必要 |

### 2.2 Azureリソース

| リソース | 用途 |
|---|---|
| App Service | フロントエンド静的ファイル配信 + Python バックエンド |
| Microsoft Foundry リソース (`kind: AIServices`) | Azure AI Speech エンドポイント + Foundry Agent Service（Prompt Agent）|
| Foundry プロジェクト | エージェント管理。エンドポイント形式: `https://<resource>.ai.azure.com/api/projects/<project>` |
| Cosmos DB for NoSQL | インタビューデータ永続化 + ベクトル検索 |
| Azure Functions (Flex Consumption) | MCP Server（インタビューデータのベクトル検索ツール提供） |
| Storage Account | Function App デプロイメントストレージ |
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
文字起こし開始（Azure Speech SDK 連続認識）
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

- **技術**: Azure AI Speech SDK（`microsoft-cognitiveservices-speech-sdk` CDN版）
  - ブラウザ向けバンドル: `https://aka.ms/csspeech/jsbrowserpackageraw`（`<script>` タグで読み込み）
  - グローバル変数 `window.SpeechSDK` として利用可能
- **接続方式**: Speech SDK がブラウザ内で直接 Azure Speech Service のWebSocketエンドポイントに接続
  - SDK が内部的にマイク入力の取得（`getUserMedia`）、音声エンコーディング、WebSocket通信を一括管理
  - 認識モード: **連続会話文字起こし**（`ConversationTranscriber.startTranscribingAsync`）で話者分離を有効化
- **音声入力**: `AudioConfig.fromDefaultMicrophoneInput()` でブラウザのデフォルトマイクを使用
  - Speech SDK が内部的に `navigator.mediaDevices.getUserMedia()` を呼び出す
  - 単一マイクのミックス音声から Azure Speech の音声クラスタリングにより話者を自動分離
- **文字起こしイベント**:
  - `transcribed` イベント: 確定された認識結果（`ResultReason.RecognizedSpeech`）→ `e.result.text` と `e.result.speakerId` を取得しエージェントへの入力に使用
  - `transcribing` イベント: 中間結果（ログのみ）
  - `canceled` イベント: エラーハンドリング
  - `sessionStopped` イベント: セッション終了ログ
- **SpeechConfig 設定**:
  - `speechRecognitionLanguage`: `"ja-JP"` または `"en-US"`（言語トグルに連動）
  - `SpeechServiceConnection_EndSilenceTimeoutMs`: `"500"`（500ms の無音でフレーズ確定）
- **ノイズ抑制**:
  - Speech SDK の Microsoft Audio Stack（MAS）は JavaScript 環境では利用不可（C#/C++/Java のみ）
  - ブラウザの WebRTC ノイズ抑制（`getUserMedia` のデフォルト `noiseSuppression: true`）に依存
  - Speech SDK の `fromDefaultMicrophoneInput()` がブラウザのデフォルト設定を使用するため自動的に有効
- **話者識別（ダイアライゼーション）**:
  - `ConversationTranscriber` がサービス側で話者を自動分離し、`speakerId` として `"Guest-1"`, `"Guest-2"`, ...（初期や特定不能時は `"Unknown"`）を付与する
  - 事前の声紋登録は不要
  - Interviewer / Interviewee の属性区別までは行わない（エージェントが文脈から推測）
  - UI では発言テキストの先頭に `●` を表示し、`speakerId` ごとに色分けする（`Guest-1` など話者名自体は UI には出さない）
  - バックエンドへは WebSocket 経由で `speakerId` を送信・Cosmos DB `transcript_entry` に保存
  - エージェント入力・レポート生成時は各行を `[Guest-1] text` 形式に整形して渡し、AI が話者を区別可能にする
- **文字起こしテキストの流れ**:
  1. Speech SDK がブラウザのマイクから音声を取得し、Azure Speech Service に送信
  2. `transcribed` イベントで確定テキストと `speakerId` を受信
  3. 左ペインにリアルタイム表示（`●` + テキスト）
  4. WebSocket 経由でバックエンドに送信（`speakerId` 含む）
  5. バックエンドが Cosmos DB に保存 + Foundry Agent Service に話者タグ付きで入力
- **ブラウザ認証**:
  - `DefaultAzureCredential` はブラウザでは使用不可
  - バックエンド API `GET /api/speech/token` で Microsoft Entra ID トークン（scope: `https://cognitiveservices.azure.com/.default`）を取得
  - AI Foundry リソースのエンドポイント（`services.ai.azure.com`）を `cognitiveservices.azure.com` ドメインに変換して Speech SDK に渡す
  - `SpeechConfig.fromEndpoint(URL, TokenCredential)` で認証。`TokenCredential` オブジェクトは `getToken()` メソッドでトークンを返す
  - **注意**: `services.ai.azure.com` ドメインは AI Foundry API用であり、Speech SDK のWebSocketパスには対応しない。同一リソースの `cognitiveservices.azure.com` ドメインを使用する必要がある

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
- 文字起こしには話者ID（`[Guest-1]`, `[Guest-2]`, `[Unknown]` など）が付与される。Interviewer / Interviewee の属性までは識別されないため、発言者の役割は文脈から推測すること
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

- インタビュー終了時に以下のフローで処理を実行:
  1. **トランスクリプトキュレーション**: ノイズ除去・重複コンテキスト排除（内容は保持）
  2. **Cosmos DB 保存**: キュレーション結果 + インタビュー詳細（対象者・所属・日時・開始/終了時間）を `interview_records` コンテナに保存
  3. **レポート生成**: キュレーション済みテキストを用いてレポート生成エージェントがマークダウンレポートを生成
  4. **ベクトル化**: キュレーション結果 + インタビュー詳細 + レポートを `text-embedding-3-small` でベクトル化し `interview_records` に保存
- **入力**: Cosmos DB から全会話履歴 + エージェント提示内容 + インタビュー詳細情報を取得
- **出力**: マークダウン形式のレポート（エキスパートの暗黙知・ノウハウ抽出に特化）
- **処理方式**: 非同期実行（FastAPI の `BackgroundTasks`）
- レポート生成完了後、WebSocket で `report_ready` を送信し、左ペインの「レポート表示」ボタンがクリック可能
- レポートは Cosmos DB に保存
- 生成状況は `GET /api/interviews/{id}/report/status` でも確認可能

#### MCP Server（ベクトル検索ツール）

レポート生成後にベクトル化されたインタビューデータに対して、Azure Functions (Flex Consumption) ベースの MCP Server が 3 つのツールを提供:

| ツール名 | 引数 | 応答 |
|---|---|---|
| `search_interviews` | `query` (string, 必須), `top_n` (number) | クエリをベクトル検索し、関連インタビューの対象者・所属・日時・開始時間・IDを返却 |
| `get_interview_report` | `id` (string, 必須) | IDに対応するレポート + 対象者・所属・日時・開始/終了時間を返却 |
| `get_interview_details` | `id` (string, 必須) | キュレーション結果・インタビュー詳細・日時・レポートの全情報を返却 |

接続エンドポイント: `https://<function-app>.azurewebsites.net/runtime/webhooks/mcp`（Streamable HTTP）

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
  "speakerId": "Guest-1",
  "timestamp": "ISO 8601 datetime",
  "sequenceNumber": 1
}
```

- `speakerId`: Azure Speech `ConversationTranscriber` が付与する話者ID（例: `"Guest-1"`, `"Guest-2"`, `"Unknown"`）
- 既存の `speakerId` 未定義ドキュメントとの下位互換性のため、フィールドは空文字列を許容する

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

#### コンテナ: `interview_records`

パーティションキー: `/interviewId`

ベクトル検索対応コンテナ。レポート生成完了後にキュレーション結果・インタビュー詳細・レポート・ベクトルエンベディングを保存。MCP Serverがベクトル検索に使用。

```json
{
  "id": "interviewId",
  "interviewId": "uuid",
  "type": "interview_record",
  "intervieweeName": "対象者名",
  "intervieweeAffiliation": "所属",
  "relatedInfo": "関連情報",
  "goal": "ゴール",
  "interviewDate": "ISO 8601 datetime",
  "startTime": "ISO 8601 datetime",
  "endTime": "ISO 8601 datetime",
  "curatedTranscript": "キュレーション済みトランスクリプト",
  "reportMarkdown": "レポートのマークダウン",
  "embedding": [0.123, -0.456, ...],
  "createdAt": "ISO 8601 datetime",
  "updatedAt": "ISO 8601 datetime"
}
```

> **ベクトルインデックス**: `quantizedFlat` タイプ、cosine 距離、1536 次元（text-embedding-3-small）
> **制約**: `EnableNoSQLVectorSearch` capability の有効化が必要（伝搬に最大15分）

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
| GET | `/api/speech/token` | Azure Speech Service 用 Entra ID トークン発行 |

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
│   │   ├── speech.js                  # Azure Speech SDK 連続認識
│   │   ├── websocket.js               # バックエンド WebSocket 通信 + 無音検出
│   │   ├── ui.js                      # UI 操作・レンダリング
│   │   └── modal.js                   # インタビュー詳細登録モーダル
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
│   │   ├── speech.py                  # Speech Service トークン発行 API
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
│   │   ├── auth-postprovision.ps1     # リダイレクト URI 設定 + ベクトルコンテナ作成 (Windows)
│   │   ├── auth-postprovision.sh      # リダイレクト URI 設定 + ベクトルコンテナ作成 (Linux/macOS)
│   │   ├── create-vector-container.ps1  # Cosmos DB ベクトルコンテナ作成（リトライ付き）
│   │   └── create-vector-container.sh   # Cosmos DB ベクトルコンテナ作成（リトライ付き）
│   └── modules/
│       ├── app-service.bicep          # App Service + Plan + Easy Auth (authsettingsV2)
│       ├── cosmos-db.bicep            # Cosmos DB + コンテナ
│       ├── cosmos-rbac.bicep          # Cosmos DB RBAC
│       ├── ai-foundry.bicep           # New Foundry + Embedding モデルデプロイ
│       ├── ai-rbac.bicep              # AI Foundry RBAC
│       └── function-app.bicep         # Azure Functions (Flex Consumption) MCP Server
├── mcp-server/
│   ├── function_app.py                # MCP ツールトリガー（3ツール）
│   ├── host.json                      # Functions ホスト設定
│   └── requirements.txt               # Python 依存パッケージ
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

> **重要な実装上の決定**: リアルタイム文字起こしには Azure AI Speech SDK（`microsoft-cognitiveservices-speech-sdk` CDN版）の連続会話文字起こし（`ConversationTranscriber.startTranscribingAsync`）を使用し、話者分離を利用する。Speech SDK がブラウザでマイク入力・WebSocket通信を一括管理するため、AudioWorklet や手動のPCM16変換は不要。フロントエンドに npm 依存パッケージはない（Vite のみ devDependencies）。

**フロントエンドのビルド**: Vite でバンドルし `frontend/dist/` に出力。`azd` の prepackage フックで自動実行。

### 8.2 Backend (pip)

```
fastapi>=0.110.0
uvicorn>=0.29.0
websockets>=12.0
azure-ai-projects>=2.0.0
azure-identity>=1.17.0
azure-cosmos>=4.7.0
openai>=1.0.0
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

> **注意**: Speech Service の認証には `Cognitive Services User` **と** `Azure AI User` の**両方**のロールが必要。

### 9.4 Speech トークン API のセキュリティ

- `GET /api/speech/token` エンドポイントは Easy Auth により認証済みユーザーのみアクセス可能
- トークンの有効期限を応答に含め、フロントエンドが期限前に再取得できるようにする

### 9.5 WebSocket 接続の認証

- `/ws/interview/{id}` WebSocket エンドポイントは Easy Auth のセッション Cookie により認証される
- 不正な接続は直ちに切断する

### 9.6 デプロイ

- GitHub Actions + OIDC（フェデレーション資格情報）を使用
- Basic 認証（SCM/FTP）は無効化（組織ポリシー）
- publish-profile シークレットは使用不可

---

## 10. Azure Speech SDK 詳細仕様

### 10.1 ブラウザ認証フロー

Azure Speech Service は認証トークンによるアクセスを使用する。ブラウザでは `DefaultAzureCredential` が使用できないため、以下のフローを採用する:

```
Browser                          Backend                       Entra ID
  │                                │                              │
  │ GET /api/speech/token          │                              │
  │──────────────────────────────▶│                              │
  │                                │ DefaultAzureCredential       │
  │                                │  .get_token(scope)           │
  │                                │─────────────────────────────▶│
  │                                │◀─────────────────────────────│
  │                                │  Bearer token                │
  │◀──────────────────────────────│                              │
  │  { token, endpoint, region }   │                              │
  │                                │                              │
  │ Speech SDK 連続認識開始         │                              │
  │  (SpeechConfig + token)        │                              │
```

**バックエンド側トークン発行（Python）:**

```python
from azure.identity import DefaultAzureCredential

credential = DefaultAzureCredential()

@app.get("/api/speech/token")
async def get_speech_token():
    token = credential.get_token("https://cognitiveservices.azure.com/.default")
    return {
        "token": token.token,
        "endpoint": AZURE_SPEECH_ENDPOINT,  # e.g. "https://<resource>.cognitiveservices.azure.com"
        "region": AZURE_SPEECH_REGION,      # e.g. "japaneast"
        "expiresOn": token.expires_on,
    }
```

### 10.2 ブラウザ側実装（ConversationTranscriber による連続会話文字起こし）

Azure Speech SDK（CDN版 `microsoft-cognitiveservices-speech-sdk`）の `ConversationTranscriber` を使用し、話者分離付きのリアルタイム文字起こしを行う。

```javascript
// バックエンドからトークンを取得
const res = await fetch("/api/speech/token");
const { token, endpoint } = await res.json();

// services.ai.azure.com → cognitiveservices.azure.com に変換
const speechHost = endpoint.replace(".services.ai.azure.com", ".cognitiveservices.azure.com");

// TokenCredential を構築 (Entra ID Bearer Token)
const tokenCredential = {
  getToken: () => Promise.resolve({
    token,
    expiresOnTimestamp: Date.now() + 3600 * 1000,
  }),
};

// SpeechConfig を endpoint + TokenCredential で構築
const speechConfig = SpeechSDK.SpeechConfig.fromEndpoint(new URL(speechHost), tokenCredential);
speechConfig.speechRecognitionLanguage = "ja-JP";
speechConfig.setProperty(
  SpeechSDK.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs,
  "500"
);

// マイク入力の AudioConfig
const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();

// ConversationTranscriber を作成（話者分離は自動有効化）
const transcriber = new SpeechSDK.ConversationTranscriber(speechConfig, audioConfig);

// 確定結果イベント（text + speakerId）
transcriber.transcribed = (sender, event) => {
  if (event.result.reason === SpeechSDK.ResultReason.RecognizedSpeech) {
    const speakerId = event.result.speakerId || "Unknown"; // "Guest-1", "Guest-2", "Unknown"
    displayTranscript(event.result.text, speakerId);
    sendToBackend(event.result.text, speakerId);
  }
};

transcriber.transcribing = (sender, event) => {
  // 中間結果（ログのみ）
};

// 連続会話文字起こしを開始
transcriber.startTranscribingAsync();
```

### 10.3 Speech SDK 設定の詳細

| パラメータ | 値 | 理由 |
|---|---|---|
| 使用クラス | `ConversationTranscriber` | 話者分離を有効化（`speakerId` 自動付与） |
| `speechRecognitionLanguage` | `"ja-JP"` / `"en-US"` | 言語トグルに連動 |
| `AudioConfig` | `fromDefaultMicrophoneInput()` | ブラウザのデフォルトマイクを使用 |
| `SpeechServiceConnection_EndSilenceTimeoutMs` | `"500"` | 500ms の無音でフレーズ確定 |
| 認証方式 | `TokenCredential` オブジェクト | Managed Identity ベースの Entra ID トークン認証 |
| エンドポイント形式 | `*.cognitiveservices.azure.com` | Speech SDK が要求するドメイン形式（`services.ai.azure.com` から変換）|

> **設計判断の根拠**: `ConversationTranscriber` による連続会話文字起こし（`startTranscribingAsync`）を使用することで、SDK がマイク入力・WebSocket通信・音声エンコーディングと話者分離を一括管理する。AudioWorklet や手動のPCM16変換が不要となり、実装がシンプルになる。`transcribed` イベントで確定テキストと `speakerId`、`transcribing` イベントで中間結果をリアルタイムに取得できる。

---

## 11. 非機能要件

| 項目 | 要件 |
|---|---|
| レイテンシ | 文字起こし: 1秒以内の遅延。エージェント応答: 5秒以内目標 |
| 同時接続 | 要確認（質問事項参照） |
| UI | モダンデザイン、レスポンシブ、ダークモード非対応でも可 |
| ブラウザ対応 | Chrome, Edge（最新版）。Safari は Speech SDK の互換性要確認 |
| データ保持 | 要確認（質問事項参照） |

### 11.1 エラーハンドリング・リカバリ

| シナリオ | 対応方針 |
|---|---|
| Speech SDK 切断 | 自動再接続（exponential backoff）。再接続時にトークンを再取得 |
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
| Azure Speech SDK 概要 | https://learn.microsoft.com/azure/ai-services/speech-service/speech-sdk |
| Speech SDK JS クイックスタート | https://learn.microsoft.com/azure/ai-services/speech-service/get-started-speech-to-text?pivots=programming-language-javascript |
| Speech SDK CDN リファレンス | https://aka.ms/csspeech/jsbrowserpackage |
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

### 13.2 Azure Speech SDK の連続会話文字起こし（話者分離付き）について

- Azure Speech SDK の `ConversationTranscriber.startTranscribingAsync` によりリアルタイム文字起こしと話者分離を同時に実現
- `transcribed` イベントで確定テキストと `speakerId`（`"Guest-1"`, `"Guest-2"`, `"Unknown"`）、`transcribing` イベントで中間結果を取得
- 話者分離は SDK 内部で自動有効化される（`isSpeakerDiarizationEnabled = true`）ため、追加設定不要
- 事前の声紋登録は不要。サービスが単一マイクのミックス音声から音声クラスタリングで話者を自動分離
- Interviewer / Interviewee の属性判別は行わない（エージェントが文脈から推測）
- SDK がマイク入力・WebSocket通信・音声エンコーディングを一括管理するため、AudioWorklet や手動のPCM16変換は不要
- CDN 版（`microsoft-cognitiveservices-speech-sdk`）を使用し、npm 依存なしでブラウザで動作

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
