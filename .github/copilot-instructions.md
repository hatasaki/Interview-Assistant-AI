# Project Guidelines

## Azure Organization Policies

このプロジェクトのAzure環境には以下の組織ポリシーが適用されている。コード生成・レビュー・設計時に必ず遵守すること。

### 1. 認証: Managed Identity 必須

- Azureリソース間の接続には **Managed Identity 認証のみ** を使用すること
- アクセスキー、接続文字列にキーを含む方式、SASトークンによる認証は **禁止**
- SDKでは `DefaultAzureCredential` または `ManagedIdentityCredential` を使用する
- Key Vault、Storage、SQL Database、Service Bus 等すべてのサービス間接続が対象
- ローカル開発時は `DefaultAzureCredential` のフォールバック（Azure CLI / Visual Studio 認証）を利用する

### 2. デプロイ: Basic 認証の禁止

- App Service および Azure Functions の **Basic 認証（SCM / FTP）は無効化** されている
- 発行プロファイル（Publish Profile）によるデプロイは使用不可
- デプロイ方法は以下のいずれかを使用すること:
  - **GitHub Actions + OIDC（フェデレーション資格情報）** — 推奨
  - **Azure CLI (`az webapp deploy`)** + Managed Identity / サービスプリンシパル
  - **Azure DevOps パイプライン** + サービス接続（Workload Identity Federation）
- GitHub Actions のワークフローで `publish-profile` シークレットは使用しないこと
