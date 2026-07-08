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

output name string = webApp.name
output url string = 'https://${webApp.properties.defaultHostName}'
output identityPrincipalId string = webApp.identity.principalId
