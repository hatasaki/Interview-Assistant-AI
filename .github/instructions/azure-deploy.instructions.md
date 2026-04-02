---
description: "Use when creating or modifying CI/CD pipelines, GitHub Actions workflows, or Azure DevOps pipelines for deploying to Azure. Covers OIDC-based deployment and basic auth prohibition."
applyTo: ".github/workflows/**, **/azure-pipelines*.yml, **/pipeline*.yml"
---

# Azure Deployment Guidelines

## Basic 認証が無効のため注意

- `publish-profile` シークレットを使ったデプロイは動作しない
- `azure/webapps-deploy` アクションで `publish-profile` パラメータは使用不可
- FTP / ZIP deploy with Basic auth も使用不可

## 推奨: GitHub Actions + OIDC (Federated Credentials)

```yaml
permissions:
  id-token: write
  contents: read

steps:
  - uses: actions/checkout@v4

  - uses: azure/login@v2
    with:
      client-id: ${{ secrets.AZURE_CLIENT_ID }}
      tenant-id: ${{ secrets.AZURE_TENANT_ID }}
      subscription-id: ${{ secrets.AZURE_SUBSCRIPTION_ID }}

  - uses: azure/webapps-deploy@v3
    with:
      app-name: ${{ env.APP_NAME }}
      # publish-profile は使用しない
```

## 必要な Azure 側の設定

1. Microsoft Entra ID にアプリ登録を作成
2. フェデレーション資格情報を追加（GitHub リポジトリ / ブランチを指定）
3. App Service に対する `Website Contributor` ロールを割り当て
4. GitHub リポジトリのシークレットに `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` を設定

## 禁止パターン

- `secrets.AZURE_WEBAPP_PUBLISH_PROFILE` の使用
- `az webapp deployment source config-zip --src` にユーザー名/パスワードを渡す方式
- FTP によるファイルアップロード
