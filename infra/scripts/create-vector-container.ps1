#!/usr/bin/env pwsh
# Creates the interview_records container with vector embedding policy.
# Called as a post-provision hook because the EnableNoSQLVectorSearch
# capability requires up to 15 minutes to propagate after account creation.

$ErrorActionPreference = "Stop"

$cosmosAccountName = (azd env get-value AZURE_COSMOS_DB_ENDPOINT) -replace 'https://(.+?)\.documents\.azure\.com.*', '$1'
$resourceGroup     = azd env get-value AZURE_RESOURCE_GROUP
$databaseName      = "interview-assistant-db"
$containerName     = "interview_records"
$subscriptionId    = (az account show --query id -o tsv)

Write-Host ""
Write-Host "=== Creating vector-enabled container '$containerName' ==="
Write-Host "  Account       : $cosmosAccountName"
Write-Host "  Resource Group: $resourceGroup"
Write-Host ""

# Check if container already exists
$existing = az cosmosdb sql container show `
    --resource-group $resourceGroup `
    --account-name $cosmosAccountName `
    --database-name $databaseName `
    --name $containerName `
    --query "resource.id" -o tsv 2>$null

if ($existing -eq $containerName) {
    Write-Host "Container '$containerName' already exists. Skipping."
    exit 0
}

# Build the ARM request body
$body = @{
    properties = @{
        resource = @{
            id           = $containerName
            partitionKey = @{ paths = @("/interviewId"); kind = "Hash" }
            indexingPolicy = @{
                indexingMode  = "consistent"
                includedPaths = @(@{ path = "/*" })
                excludedPaths = @(
                    @{ path = "/embedding/*" }
                )
                vectorIndexes = @(
                    @{ path = "/embedding"; type = "quantizedFlat" }
                )
            }
            vectorEmbeddingPolicy = @{
                vectorEmbeddings = @(
                    @{
                        path             = "/embedding"
                        dataType         = "float32"
                        distanceFunction = "cosine"
                        dimensions       = 1536
                    }
                )
            }
        }
    }
} | ConvertTo-Json -Depth 10

$bodyFile = [System.IO.Path]::GetTempFileName()
$body | Out-File $bodyFile -Encoding utf8

$uri = "/subscriptions/$subscriptionId/resourceGroups/$resourceGroup/providers/Microsoft.DocumentDB/databaseAccounts/$cosmosAccountName/sqlDatabases/$databaseName/containers/${containerName}?api-version=2024-05-15"

# Capability propagation can take up to 15 minutes.
# Retry with 30-second intervals for up to ~16 minutes.
$maxRetries = 32
$retryDelay = 30

Write-Host "Waiting for EnableNoSQLVectorSearch capability to propagate..."
Write-Host "(This may take several minutes on first deployment)"
Write-Host ""

for ($i = 1; $i -le $maxRetries; $i++) {
    $elapsed = ($i - 1) * $retryDelay
    $elapsedMin = [math]::Floor($elapsed / 60)
    $elapsedSec = $elapsed % 60
    Write-Host "  Attempt $i/$maxRetries (elapsed: ${elapsedMin}m${elapsedSec}s) ..."

    $result = az rest --method put --uri $uri --body "@$bodyFile" 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "Container '$containerName' created successfully!"
        Remove-Item $bodyFile -ErrorAction SilentlyContinue
        exit 0
    }

    $errorText = $result -join "`n"
    if ($errorText -match "capability has not been enabled") {
        Write-Host "    -> Capability not yet propagated. Retrying in ${retryDelay}s ..."
        Start-Sleep -Seconds $retryDelay
    }
    elseif ($errorText -match "already exists") {
        Write-Host ""
        Write-Host "Container '$containerName' already exists."
        Remove-Item $bodyFile -ErrorAction SilentlyContinue
        exit 0
    }
    else {
        Write-Host "Unexpected error:"
        Write-Host $errorText
        Remove-Item $bodyFile -ErrorAction SilentlyContinue
        exit 1
    }
}

Write-Host ""
Write-Host "ERROR: Vector search capability did not propagate within $([math]::Floor($maxRetries * $retryDelay / 60)) minutes."
Write-Host "Please wait a few more minutes and run: azd provision"
Remove-Item $bodyFile -ErrorAction SilentlyContinue
exit 1
