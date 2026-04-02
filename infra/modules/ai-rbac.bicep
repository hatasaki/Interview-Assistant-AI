@description('AI Foundry resource name')
param aiFoundryResourceName string

@description('Principal ID to assign roles to')
param principalId string

// Reference existing New Foundry resource
resource aiFoundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: aiFoundryResourceName
}

// Cognitive Services User on Foundry resource
resource cognitiveServicesUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, principalId, 'a97b65f3-24c7-4388-baec-2e87135dc908')
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// Azure AI User on Foundry resource
resource aiUserOnFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundry.id, principalId, '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  scope: aiFoundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
