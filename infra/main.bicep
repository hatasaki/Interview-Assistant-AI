targetScope = 'subscription'

@minLength(1)
@maxLength(64)
@description('Name of the environment (e.g., dev, staging, prod)')
param environmentName string

@minLength(1)
@description('Primary location for all resources')
param location string

@description('Name of the AI Foundry resource (leave empty for auto-generated)')
param aiFoundryResourceName string = ''

@description('Name of the AI Foundry project (leave empty for auto-generated)')
param aiFoundryProjectName string = ''

@description('Model deployment name for Foundry Agent')
param agentModel string = 'gpt-4o'

@description('Embedding model name')
param embeddingModel string = 'text-embedding-3-small'

@description('Entra ID App Registration client ID for Easy Auth')
param authClientId string = ''

@secure()
@description('Entra ID App Registration client secret for Easy Auth')
param authClientSecret string = ''

var abbrs = loadJsonContent('abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

module cosmosDb 'modules/cosmos-db.bicep' = {
  name: 'cosmos-db'
  scope: rg
  params: {
    name: '${abbrs.documentDBDatabaseAccounts}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
  }
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  scope: rg
  params: {
    workspaceName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    appInsightsName: '${abbrs.insightsComponents}${resourceToken}'
    location: location
    tags: tags
  }
}

module aiFoundry 'modules/ai-foundry.bicep' = {
  name: 'ai-foundry'
  scope: rg
  params: {
    aiFoundryResourceName: !empty(aiFoundryResourceName) ? aiFoundryResourceName : '${abbrs.cognitiveServicesAccounts}${resourceToken}'
    aiFoundryProjectName: !empty(aiFoundryProjectName) ? aiFoundryProjectName : 'proj-${resourceToken}'
    location: location
    tags: tags
    agentModel: agentModel
    embeddingModel: embeddingModel
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
  }
}

module appService 'modules/app-service.bicep' = {
  name: 'app-service'
  scope: rg
  params: {
    name: '${abbrs.webSitesAppService}${resourceToken}'
    planName: '${abbrs.webServerFarms}${resourceToken}'
    location: location
    tags: tags
    cosmosDbAccountName: cosmosDb.outputs.accountName
    aiFoundryEndpoint: aiFoundry.outputs.projectEndpoint
    speechEndpoint: aiFoundry.outputs.aiServicesEndpoint
    agentModel: agentModel
    embeddingModel: embeddingModel
    authClientId: authClientId
    authClientSecret: authClientSecret
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

module mcpFunctionApp 'modules/function-app.bicep' = {
  name: 'mcp-function-app'
  scope: rg
  params: {
    name: '${abbrs.functionApp}${resourceToken}'
    planName: '${abbrs.functionAppPlan}${resourceToken}'
    storageName: '${abbrs.storageAccounts}${resourceToken}'
    location: location
    tags: tags
    cosmosDbAccountName: cosmosDb.outputs.accountName
    aiFoundryEndpoint: aiFoundry.outputs.projectEndpoint
    embeddingModel: embeddingModel
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

// RBAC: App Service -> Cosmos DB (Cosmos DB Built-in Data Contributor)
module cosmosRbac 'modules/cosmos-rbac.bicep' = {
  name: 'cosmos-rbac'
  scope: rg
  params: {
    cosmosDbAccountName: cosmosDb.outputs.accountName
    principalId: appService.outputs.identityPrincipalId
  }
}

// RBAC: App Service -> AI Foundry (Azure AI User)
module aiFoundryRbac 'modules/ai-rbac.bicep' = {
  name: 'ai-foundry-rbac'
  scope: rg
  params: {
    aiFoundryResourceName: aiFoundry.outputs.aiFoundryName
    principalId: appService.outputs.identityPrincipalId
  }
}

// RBAC: MCP Function App -> Cosmos DB (Cosmos DB Built-in Data Contributor)
module mcpCosmosRbac 'modules/cosmos-rbac.bicep' = {
  name: 'mcp-cosmos-rbac'
  scope: rg
  params: {
    cosmosDbAccountName: cosmosDb.outputs.accountName
    principalId: mcpFunctionApp.outputs.identityPrincipalId
  }
}

// RBAC: MCP Function App -> AI Foundry (Azure AI User)
module mcpAiFoundryRbac 'modules/ai-rbac.bicep' = {
  name: 'mcp-ai-foundry-rbac'
  scope: rg
  params: {
    aiFoundryResourceName: aiFoundry.outputs.aiFoundryName
    principalId: mcpFunctionApp.outputs.identityPrincipalId
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_COSMOS_DB_ENDPOINT string = cosmosDb.outputs.endpoint
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
output AZURE_SPEECH_ENDPOINT string = aiFoundry.outputs.aiServicesEndpoint
output AZURE_AGENT_MODEL string = agentModel
output AZURE_EMBEDDING_MODEL string = embeddingModel
output AZURE_WEBAPP_NAME string = appService.outputs.name
output AZURE_WEBAPP_URL string = appService.outputs.url
output AZURE_MCP_FUNCTION_NAME string = mcpFunctionApp.outputs.name
output AZURE_MCP_FUNCTION_URL string = mcpFunctionApp.outputs.url
output AZURE_LOG_ANALYTICS_WORKSPACE_NAME string = monitoring.outputs.workspaceName
output AZURE_APPLICATION_INSIGHTS_NAME string = monitoring.outputs.appInsightsName
