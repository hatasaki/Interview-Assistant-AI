@description('Cosmos DB account name')
param name string

@description('Location for the Cosmos DB account')
param location string

@description('Tags for the resources')
param tags object = {}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: name
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    capabilities: [
      {
        name: 'EnableServerless'
      }
      {
        name: 'EnableNoSQLVectorSearch'
      }
    ]
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmosAccount
  name: 'interview-assistant-db'
  properties: {
    resource: {
      id: 'interview-assistant-db'
    }
  }
}

resource interviewsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'interviews'
  properties: {
    resource: {
      id: 'interviews'
      partitionKey: {
        paths: ['/interviewId']
        kind: 'Hash'
      }
    }
  }
}

resource transcriptsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'transcripts'
  properties: {
    resource: {
      id: 'transcripts'
      partitionKey: {
        paths: ['/interviewId']
        kind: 'Hash'
      }
    }
  }
}

resource agentResponsesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'agent_responses'
  properties: {
    resource: {
      id: 'agent_responses'
      partitionKey: {
        paths: ['/interviewId']
        kind: 'Hash'
      }
    }
  }
}

resource chatMessagesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'chat_messages'
  properties: {
    resource: {
      id: 'chat_messages'
      partitionKey: {
        paths: ['/interviewId']
        kind: 'Hash'
      }
    }
  }
}

resource reportsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: database
  name: 'reports'
  properties: {
    resource: {
      id: 'reports'
      partitionKey: {
        paths: ['/interviewId']
        kind: 'Hash'
      }
    }
  }
}

// NOTE: interview_records container with vector embedding policy is created
// by the post-provision script (create-vector-container) because the
// EnableNoSQLVectorSearch capability requires up to 15 minutes to propagate
// after account creation. Creating it inline would cause deployment failures.

output accountName string = cosmosAccount.name
output endpoint string = cosmosAccount.properties.documentEndpoint
