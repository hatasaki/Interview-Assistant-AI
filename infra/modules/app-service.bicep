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

@description('Voice Live API endpoint')
param voiceLiveEndpoint string

@description('Voice Live model name')
param voiceLiveModel string

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
          name: 'AZURE_VOICELIVE_ENDPOINT'
          value: voiceLiveEndpoint
        }
        {
          name: 'AZURE_VOICELIVE_MODEL'
          value: voiceLiveModel
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
