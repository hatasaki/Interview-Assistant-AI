---
description: "Use when creating or modifying Azure infrastructure definitions: Bicep, Terraform, ARM templates, or azure.yaml. Covers Managed Identity configuration and key-based auth prohibition."
applyTo: "**/*.bicep, **/*.tf, **/*.tfvars, **/arm-template*.json, **/azure.yaml"
---

# Azure Infrastructure Guidelines

## Managed Identity の設定

- すべてのリソースで `identity` ブロックに `SystemAssigned` または `UserAssigned` を指定する
- リソース間のアクセス制御には Azure RBAC ロール割り当てを使用する（キーではなく）

### Bicep の例

```bicep
resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    siteConfig: {
      ftpsState: 'Disabled'
    }
  }
}

// Storage への RBAC ロール割り当て例
resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe') // Storage Blob Data Contributor
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}
```

## 禁止パターン

- `listKeys()` や `listConnectionStrings()` をリソース接続に使わない
- `storageAccountAccessKey` や `primaryKey` をアプリ設定に直接設定しない
- App Service / Functions の `basicPublishingCredentialsPolicies` は `allow: false` にする

## Basic 認証の無効化 (Bicep)

```bicep
resource scmBasicAuth 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: webApp
  name: 'scm'
  properties: {
    allow: false
  }
}

resource ftpBasicAuth 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: webApp
  name: 'ftp'
  properties: {
    allow: false
  }
}
```
