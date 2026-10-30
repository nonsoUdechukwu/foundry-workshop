targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('Name of the azd environment. Used to derive resource names.')
param environmentName string

@description('Azure region for all resources. Must offer the chat, embedding and (optional) fine-tuning models below.')
@allowed([
  'swedencentral'
  'eastus2'
  'northcentralus'
  'westus3'
  'francecentral'
  'australiaeast'
])
param location string = 'swedencentral'

@description('Object ID of the user or service principal running the labs. azd fills this in automatically.')
param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

@description('Chat model used by every lab.')
param chatModelName string = 'gpt-5.4-mini'
param chatModelVersion string = '2026-03-17'
param chatModelCapacity int = 100

@description('Embedding model used by RAG and memory labs.')
param embeddingModelName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingModelCapacity int = 100

@description('Set to false to skip Azure AI Search (Module 4 then needs your own index).')
param deploySearch bool = true

@description('Region for Azure AI Search. Empty = same as location. Override if Search capacity is constrained there.')
param searchLocation string = ''

var tags = {
  'azd-env-name': environmentName
  workshop: 'foundry-workshop'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'foundry-workshop-resources'
  scope: rg
  params: {
    location: location
    tags: tags
    resourceToken: toLower(uniqueString(subscription().id, environmentName, location))
    principalId: principalId
    principalType: principalType
    chatModelName: chatModelName
    chatModelVersion: chatModelVersion
    chatModelCapacity: chatModelCapacity
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingModelCapacity: embeddingModelCapacity
    deploySearch: deploySearch
    searchLocation: empty(searchLocation) ? location : searchLocation
  }
}

output AZURE_LOCATION string = location
output AZURE_SUBSCRIPTION_ID string = subscription().subscriptionId
output AZURE_RESOURCE_GROUP string = rg.name
output FOUNDRY_ACCOUNT_NAME string = resources.outputs.accountName
output FOUNDRY_PROJECT_NAME string = resources.outputs.projectName
output FOUNDRY_PROJECT_ENDPOINT string = resources.outputs.projectEndpoint
output FOUNDRY_MODEL_NAME string = chatModelName
output FOUNDRY_EMBEDDING_MODEL_NAME string = embeddingModelName
output AI_SEARCH_ENDPOINT string = resources.outputs.searchEndpoint
output AI_SEARCH_CONNECTION_NAME string = resources.outputs.searchConnectionName
output FOUNDRY_RAI_POLICY_NAME string = resources.outputs.raiPolicyName
output FOUNDRY_RAI_POLICY_ID string = resources.outputs.raiPolicyId
