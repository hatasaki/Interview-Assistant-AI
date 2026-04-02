@description('AI Foundry resource name')
param aiFoundryResourceName string

@description('AI Foundry project name')
param aiFoundryProjectName string

@description('Location for the resources')
param location string

@description('Tags for the resources')
param tags object = {}

@description('Model for Foundry Agent')
param agentModel string

// ── New Foundry resource (Microsoft.CognitiveServices/accounts) ──
// See: https://learn.microsoft.com/azure/foundry/how-to/create-resource-template
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: aiFoundryResourceName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: aiFoundryResourceName
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

// ── New Foundry project (child resource of the Foundry account) ──
resource aiProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: aiFoundry
  name: aiFoundryProjectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {}
}

// ── Agent model deployment ──
resource agentDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: aiFoundry
  name: agentModel
  sku: {
    name: 'GlobalStandard'
    capacity: 30
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: agentModel
      version: '2024-08-06'
    }
  }
}

output aiFoundryName string = aiFoundry.name
output aiServicesEndpoint string = 'https://${aiFoundryResourceName}.services.ai.azure.com'
output projectName string = aiProject.name
output projectEndpoint string = 'https://${aiFoundryResourceName}.services.ai.azure.com/api/projects/${aiFoundryProjectName}'
