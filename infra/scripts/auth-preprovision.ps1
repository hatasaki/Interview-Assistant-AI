$ErrorActionPreference = "Stop"

Write-Host "=== Entra ID App Registration (preprovision) ==="

# Check if AUTH_CLIENT_ID already has a value
$existingClientId = azd env get-value AUTH_CLIENT_ID 2>$null
if ($LASTEXITCODE -ne 0) { $existingClientId = $null }

if ($existingClientId) {
    Write-Host "Entra ID App Registration already configured: $existingClientId"

    # Ensure a client secret exists
    $existingSecret = azd env get-value AUTH_CLIENT_SECRET 2>$null
    if ($LASTEXITCODE -ne 0) { $existingSecret = $null }
    if ($existingSecret) {
        Write-Host "Client secret already configured. Skipping."
        exit 0
    }
    Write-Host "Client secret not found. Creating a new one..."
    $appId = $existingClientId
}
else {
    $appDisplayName = "interview-assistant-ai-$env:AZURE_ENV_NAME"

    # Check if app registration already exists by display name
    $existingApp = az ad app list --display-name $appDisplayName --query "[0].appId" -o tsv 2>$null

    if ($existingApp -and $existingApp -ne "None") {
        $appId = $existingApp
        Write-Host "Found existing App Registration: $appId"
    }
    else {
        Write-Host "Creating Entra ID App Registration: $appDisplayName"
        $appId = az ad app create `
            --display-name $appDisplayName `
            --sign-in-audience AzureADMyOrg `
            --enable-id-token-issuance true `
            --query "appId" -o tsv

        if ($LASTEXITCODE -ne 0) { throw "Failed to create App Registration" }
        Write-Host "Created App Registration: $appId"
    }

    azd env set AUTH_CLIENT_ID $appId
}

# Create a new client secret
Write-Host "Creating client secret..."
$secret = az ad app credential reset `
    --id $appId `
    --display-name "azd-managed" `
    --years 2 `
    --query "password" -o tsv

if ($LASTEXITCODE -ne 0) { throw "Failed to create client secret" }

azd env set AUTH_CLIENT_SECRET $secret

Write-Host "=== Entra ID App Registration configured successfully ==="
