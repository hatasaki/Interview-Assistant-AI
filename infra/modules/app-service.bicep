@description('App Service name')
param name string

@description('App Service Plan name')
param planName string

@description('Location')
param location string

@description('Tags')
param tags object = {}

@description('Cosmos DB account name')
param cosmosDbAccountName string

@description('AI Foundry project endpoint')
param aiFoundryEndpoint string

@description('Azure Speech Service endpoint')
param speechEndpoint string

@description('Agent model deployment name')
param agentModel string

@description('Embedding model name')
param embeddingModel string

@description('Entra ID App Registration client ID for Easy Auth')
param authClientId string = ''

@secure()
@description('Entra ID App Registration client secret for Easy Auth')
param authClientSecret string = ''

@description('Application Insights connection string')
param appInsightsConnectionString string = ''

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' existing = {
  name: cosmosDbAccountName
}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  sku: {
    name: 'B1'
    tier: 'Basic'
  }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

resource webApp 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'backend' })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      ftpsState: 'Disabled'
      appCommandLine: 'bash startup.sh'
      appSettings: [
        {
          name: 'AZURE_COSMOS_DB_ENDPOINT'
          value: cosmosAccount.properties.documentEndpoint
        }
        {
          name: 'AZURE_AI_PROJECT_ENDPOINT'
          value: aiFoundryEndpoint
        }
        {
          name: 'AZURE_SPEECH_ENDPOINT'
          value: speechEndpoint
        }
        {
          name: 'AZURE_AGENT_MODEL'
          value: agentModel
        }
        {
          name: 'AZURE_EMBEDDING_MODEL'
          value: embeddingModel
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'false'
        }
        {
          name: 'WEBSITES_PORT'
          value: '8000'
        }
        {
          name: 'WEBSITES_CONTAINER_START_TIME_LIMIT'
          value: '600'
        }
        {
          name: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
          value: authClientSecret
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: appInsightsConnectionString
        }
        {
          name: 'OTEL_RESOURCE_ATTRIBUTES'
          value: 'service.name=interview-assistant-backend'
        }
      ]
      webSocketsEnabled: true
    }
  }
}

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

// Easy Auth: Microsoft Entra ID authentication
resource authSettings 'Microsoft.Web/sites/config@2023-12-01' = if (!empty(authClientId)) {
  parent: webApp
  name: 'authsettingsV2'
  properties: {
    globalValidation: {
      requireAuthentication: true
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
    }
    httpSettings: {
      requireHttps: true
      forwardProxy: {
        convention: 'NoProxy'
      }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: authClientId
          clientSecretSettingName: 'MICROSOFT_PROVIDER_AUTHENTICATION_SECRET'
          openIdIssuer: '${environment().authentication.loginEndpoint}${tenant().tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${authClientId}'
          ]
        }
      }
    }
    login: {
      tokenStore: {
        enabled: true
      }
    }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

output name string = webApp.name
output url string = 'https://${webApp.properties.defaultHostName}'
output identityPrincipalId string = webApp.identity.principalId
