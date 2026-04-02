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

@description('Model deployment name for Voice Live API')
param voiceLiveModel string = 'gpt-4o-mini'

@description('Model deployment name for Foundry Agent')
param agentModel string = 'gpt-4o'

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
    voiceLiveEndpoint: aiFoundry.outputs.aiServicesEndpoint
    voiceLiveModel: voiceLiveModel
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

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_COSMOS_DB_ENDPOINT string = cosmosDb.outputs.endpoint
output AZURE_AI_PROJECT_ENDPOINT string = aiFoundry.outputs.projectEndpoint
output AZURE_VOICELIVE_ENDPOINT string = aiFoundry.outputs.aiServicesEndpoint
output AZURE_VOICELIVE_MODEL string = voiceLiveModel
output AZURE_WEBAPP_NAME string = appService.outputs.name
output AZURE_WEBAPP_URL string = appService.outputs.url
