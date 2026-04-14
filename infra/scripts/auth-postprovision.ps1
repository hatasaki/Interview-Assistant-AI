$ErrorActionPreference = "Stop"

Write-Host "=== Updating Entra ID App Registration redirect URI (postprovision) ==="

$authClientId = azd env get-value AUTH_CLIENT_ID 2>$null
if ($LASTEXITCODE -ne 0 -or -not $authClientId) { throw "AUTH_CLIENT_ID not found in environment. Run preprovision first." }
$webAppUrl = azd env get-value AZURE_WEBAPP_URL 2>$null
if ($LASTEXITCODE -ne 0 -or -not $webAppUrl) { throw "AZURE_WEBAPP_URL not found in environment." }



$redirectUri = "$webAppUrl/.auth/login/aad/callback"
Write-Host "Setting redirect URI: $redirectUri"

# Update the App Registration with the redirect URI
az ad app update `
    --id $authClientId `
    --web-redirect-uris $redirectUri `
    --enable-id-token-issuance true

if ($LASTEXITCODE -ne 0) { throw "Failed to update redirect URI" }

Write-Host "=== Redirect URI updated successfully ==="

# Create the vector-enabled Cosmos DB container
& "$PSScriptRoot/create-vector-container.ps1"
