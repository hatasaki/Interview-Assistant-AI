# Interview Assistant AI

ブラウザベースのインタビュー補助 Web アプリケーション。リアルタイム文字起こし・AI エージェントによる関連情報提示・次の質問案提示を通じて Interviewer をサポートします。

## 概要

エキスパート（Interviewee）の暗黙知を素人（Interviewer）が効果的に引き出すための AI 補助ツールです。

- **リアルタイム文字起こし**: Azure Voice Live API（WebSocket 直接接続、`azure_semantic_vad_multilingual` による日本語対応）
- **補足情報提示**: 会話の途切れを検出し、専門用語・技術概念を自動検索して素人向けに解説
- **質問案生成**: ボタンクリックで文字起こし履歴に基づく効果的な次の質問を提案
- **チャット Q&A**: Interviewer がリアルタイムに AI に質問可能
- **レポート生成**: インタビュー終了後、文字起こし内容に基づくマークダウンレポートを自動生成

## アーキテクチャ

| レイヤー | 技術 |
|---|---|
| フロントエンド | JavaScript (Vanilla JS) + Vite |
| バックエンド | Python (FastAPI) on Azure App Service |
| リアルタイム文字起こし | Azure Voice Live API (直接 WebSocket 接続) |
| AI エージェント | Microsoft Foundry Agent Service (azure-ai-projects v2) |
| エージェントツール | Microsoft Learn MCP Server |
| データストア | Azure Cosmos DB for NoSQL (Serverless) |
| 認証 | Managed Identity (DefaultAzureCredential) |
| インフラ | Bicep (New Foundry: CognitiveServices/accounts + projects) |

## 前提条件

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
- [Azure Developer CLI (azd)](https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd)
- [Node.js](https://nodejs.org/) >= 18
- [Python](https://www.python.org/) >= 3.12

## デプロイ

```bash
azd auth login
azd up
```

`azd up` により以下が自動実行されます：
1. フロントエンドのビルド（`npm ci && npm run build`）→ `backend/static/` にコピー
2. Azure リソースのプロビジョニング（Bicep）
3. バックエンドのデプロイ（App Service）

## ローカル開発

### バックエンド

```bash
cd backend
pip install -r requirements.txt

export AZURE_COSMOS_DB_ENDPOINT="https://<your-cosmos>.documents.azure.com:443/"
export AZURE_AI_PROJECT_ENDPOINT="https://<resource>.services.ai.azure.com/api/projects/<project>"
export AZURE_VOICELIVE_ENDPOINT="https://<resource>.services.ai.azure.com"
export AZURE_VOICELIVE_MODEL="gpt-4o-mini"

uvicorn app:app --reload --port 8000
```

### フロントエンド

```bash
cd frontend
npm install
npm run dev
```

## プロジェクト構成

```
├── azure.yaml              # azd 構成
├── infra/                   # Bicep インフラ定義 (New Foundry)
│   ├── main.bicep
│   └── modules/
│       ├── ai-foundry.bicep    # CognitiveServices/accounts + projects
│       ├── ai-rbac.bicep
│       ├── app-service.bicep
│       ├── cosmos-db.bicep
│       └── cosmos-rbac.bicep
├── backend/
│   ├── app.py               # FastAPI エントリーポイント
│   ├── startup.sh            # App Service 起動スクリプト
│   ├── config.py
│   ├── routers/
│   │   ├── interviews.py     # REST API
│   │   ├── voicelive.py      # Voice Live トークン発行
│   │   └── websocket.py      # WebSocket (3つのエージェント役割)
│   ├── services/
│   │   ├── agent_service.py   # Foundry Agent + MCP + レポート生成
│   │   ├── cosmos_service.py
│   │   └── report_service.py
│   └── models/
├── frontend/
│   ├── index.html
│   ├── js/
│   │   ├── app.js
│   │   ├── voicelive.js      # Voice Live WebSocket 直接接続
│   │   ├── websocket.js      # バックエンド通信 + 無音検出
│   │   ├── ui.js
│   │   └── modal.js
│   ├── public/js/
│   │   └── pcm-processor.js  # AudioWorklet
│   └── css/
├── spec/
│   └── app-specification.md
└── .github/
    └── workflows/deploy.yml
```

## 補助エージェントの3つの役割

| 役割 | トリガー | 動作 |
|---|---|---|
| **補足情報** | 会話の途切れ（5秒無音） | 専門用語を検出しMCP Serverで検索、素人向け解説を表示 |
| **質問生成** | 「次の質問を生成」ボタン | 直近5000文字の文字起こしから質問案を最大3個生成 |
| **チャット** | チャットボックスで送信 | 文字起こし文脈を踏まえた回答と参照情報を提示 |

各役割は独立した会話（conversation）を使用し、コンテキストの肥大化を防止しています。

## Azure リソース

| リソース | 用途 |
|---|---|
| App Service (Linux, Python 3.12) | アプリホスティング |
| AI Foundry (CognitiveServices/accounts) | Agent Service / Voice Live API |
| Foundry Project (CognitiveServices/accounts/projects) | エージェント管理 |
| Cosmos DB for NoSQL (Serverless) | データ永続化 |

すべてのリソース間認証は **Managed Identity** を使用しています（キーベース認証は禁止）。

## 技術的な注意事項

- **Voice Live SDK の制限**: `@azure/ai-voicelive` v1.0.0-beta.3 は `input_audio_transcription` をシリアライズしないため、直接 WebSocket 接続を使用
- **ブラウザ WebSocket 認証**: `authorization` クエリパラメータで Bearer トークンを送信
- **レポート生成**: エージェント経由ではなく直接モデル呼び出し（JSON 出力制約を回避）
- **ノイズ除去**: 大量の文字起こしは90Kトークン+10K重複でチャンク分割してLLMで処理
