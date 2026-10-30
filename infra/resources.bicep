@description('Primary location for all resources.')
param location string
param tags object
param resourceToken string
param principalId string
param principalType string
param chatModelName string
param chatModelVersion string
param chatModelCapacity int
param embeddingModelName string
param embeddingModelVersion string
param embeddingModelCapacity int
param deploySearch bool
@description('Region for Azure AI Search.')
param searchLocation string = location

var accountName = 'aif-${resourceToken}'
var projectName = 'workshop'
var searchName = 'srch-${resourceToken}'
var searchConnectionName = 'workshop-search'
var raiPolicyName = 'workshop-guardrails'
var blocklistName = 'workshop-blocklist'

// Built-in role definition IDs
var roles = {
  foundryUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  foundryProjectManager: 'eadc314b-1a2d-4efa-be10-5d325db5065e'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchIndexDataReader: '1407120a-92aa-4202-b7e9-c0e197c71c8f'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
}

// ---------------------------------------------------------------------------
// Monitoring
// ---------------------------------------------------------------------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${resourceToken}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${resourceToken}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------------------------------------------------------------------
// Azure AI Search (Module 4)
// ---------------------------------------------------------------------------
resource search 'Microsoft.Search/searchServices@2025-05-01' = if (deploySearch) {
  name: searchName
  location: searchLocation
  tags: tags
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    semanticSearch: 'free'
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' }
    }
  }
}

// ---------------------------------------------------------------------------
// Microsoft Foundry account + project
// ---------------------------------------------------------------------------
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  // Account child operations must not run concurrently.
  dependsOn: [embeddingDeployment]
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Foundry Workshop'
    description: 'Project used by the Microsoft Foundry Hands-on Workshop labs.'
  }
}

// ---------------------------------------------------------------------------
// Guardrails (Module 11): custom blocklist + content filter policy
// ---------------------------------------------------------------------------
resource blocklist 'Microsoft.CognitiveServices/accounts/raiBlocklists@2025-06-01' = {
  parent: account
  name: blocklistName
  properties: {
    description: 'Terms the workshop agents must never process (Module 11).'
  }
}

resource blocklistItemCodename 'Microsoft.CognitiveServices/accounts/raiBlocklists/raiBlocklistItems@2025-06-01' = {
  parent: blocklist
  name: 'project-nightingale'
  properties: {
    pattern: 'Project Nightingale'
    isRegex: false
  }
}

resource blocklistItemCardRegex 'Microsoft.CognitiveServices/accounts/raiBlocklists/raiBlocklistItems@2025-06-01' = {
  parent: blocklist
  name: 'internal-ticket-id'
  dependsOn: [blocklistItemCodename]
  properties: {
    pattern: 'INC-\\d{6}'
    isRegex: true
  }
}

resource raiPolicy 'Microsoft.CognitiveServices/accounts/raiPolicies@2025-06-01' = {
  parent: account
  name: raiPolicyName
  dependsOn: [blocklistItemCardRegex]
  properties: {
    basePolicyName: 'Microsoft.DefaultV2'
    mode: 'Blocking'
    contentFilters: [
      { name: 'Hate', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Prompt' }
      { name: 'Hate', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Completion' }
      { name: 'Sexual', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Prompt' }
      { name: 'Sexual', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Completion' }
      { name: 'Violence', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Prompt' }
      { name: 'Violence', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Completion' }
      { name: 'Selfharm', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Prompt' }
      { name: 'Selfharm', blocking: true, enabled: true, severityThreshold: 'Low', source: 'Completion' }
      { name: 'Jailbreak', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Indirect Attack', blocking: true, enabled: true, source: 'Prompt' }
      { name: 'Protected Material Text', blocking: true, enabled: true, source: 'Completion' }
      { name: 'Protected Material Code', blocking: false, enabled: true, source: 'Completion' }
    ]
    customBlocklists: [
      { blocklistName: blocklistName, blocking: true, source: 'Prompt' }
      { blocklistName: blocklistName, blocking: true, source: 'Completion' }
    ]
  }
}

// ---------------------------------------------------------------------------
// Model deployments (serialised: the RP rejects parallel deployment writes)
// ---------------------------------------------------------------------------
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: chatModelName
  dependsOn: [raiPolicy]
  sku: {
    name: 'GlobalStandard'
    capacity: chatModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: embeddingModelName
  dependsOn: [chatDeployment]
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
  }
}

// ---------------------------------------------------------------------------
// Project connections
// ---------------------------------------------------------------------------
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'workshop-appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = if (deploySearch) {
  parent: project
  name: searchConnectionName
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${searchName}.search.windows.net'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
      location: searchLocation
    }
  }
}

// ---------------------------------------------------------------------------
// RBAC
// ---------------------------------------------------------------------------
resource userAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(account.id, principalId, roles.foundryUser)
  scope: account
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource userAiProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(account.id, principalId, roles.foundryProjectManager)
  scope: account
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryProjectManager)
  }
}

resource projectAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(account.id, project.id, roles.foundryUser)
  scope: account
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.foundryUser)
  }
}

resource userLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  // Resource-group scope so the user can query both App Insights and the workspace (M10 tracing).
  name: guid(resourceGroup().id, principalId, roles.logAnalyticsReader)
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.logAnalyticsReader)
  }
}

resource userSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch && !empty(principalId)) {
  name: guid(searchName, principalId, roles.searchIndexDataContributor)
  scope: search
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataContributor)
  }
}

resource userSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch && !empty(principalId)) {
  name: guid(searchName, principalId, roles.searchServiceContributor)
  scope: search
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}

resource projectSearchData 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch) {
  name: guid(searchName, project.id, roles.searchIndexDataReader)
  scope: search
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchIndexDataReader)
  }
}

resource projectSearchService 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (deploySearch) {
  name: guid(searchName, project.id, roles.searchServiceContributor)
  scope: search
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.searchServiceContributor)
  }
}

output accountName string = account.name
output projectName string = project.name
output projectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
output searchEndpoint string = deploySearch ? 'https://${searchName}.search.windows.net' : ''
output searchConnectionName string = deploySearch ? searchConnectionName : ''
output raiPolicyName string = raiPolicyName
output raiPolicyId string = raiPolicy.id
