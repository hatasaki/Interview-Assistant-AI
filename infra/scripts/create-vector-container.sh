#!/bin/bash
# Creates the interview_records container with vector embedding policy.
# Called as a post-provision hook because the EnableNoSQLVectorSearch
# capability requires up to 15 minutes to propagate after account creation.

set -euo pipefail

COSMOS_ENDPOINT=$(azd env get-value AZURE_COSMOS_DB_ENDPOINT)
COSMOS_ACCOUNT_NAME=$(echo "$COSMOS_ENDPOINT" | sed -E 's|https://([^.]+)\.documents\.azure\.com.*|\1|')
RESOURCE_GROUP=$(azd env get-value AZURE_RESOURCE_GROUP)
DATABASE_NAME="interview-assistant-db"
CONTAINER_NAME="interview_records"
SUBSCRIPTION_ID=$(az account show --query id -o tsv)

echo ""
echo "=== Creating vector-enabled container '$CONTAINER_NAME' ==="
echo "  Account       : $COSMOS_ACCOUNT_NAME"
echo "  Resource Group: $RESOURCE_GROUP"
echo ""

# Check if container already exists
EXISTING=$(az cosmosdb sql container show \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$COSMOS_ACCOUNT_NAME" \
    --database-name "$DATABASE_NAME" \
    --name "$CONTAINER_NAME" \
    --query "resource.id" -o tsv 2>/dev/null || true)

if [ "$EXISTING" = "$CONTAINER_NAME" ]; then
    echo "Container '$CONTAINER_NAME' already exists. Skipping."
    exit 0
fi

# Build the ARM request body
BODY_FILE=$(mktemp)
trap 'rm -f "$BODY_FILE"' EXIT
cat > "$BODY_FILE" <<'EOF'
{
  "properties": {
    "resource": {
      "id": "interview_records",
      "partitionKey": {"paths": ["/interviewId"], "kind": "Hash"},
      "indexingPolicy": {
        "indexingMode": "consistent",
        "includedPaths": [{"path": "/*"}],
        "excludedPaths": [{"path": "/embedding/*"}],
        "vectorIndexes": [{"path": "/embedding", "type": "quantizedFlat"}]
      },
      "vectorEmbeddingPolicy": {
        "vectorEmbeddings": [{
          "path": "/embedding",
          "dataType": "float32",
          "distanceFunction": "cosine",
          "dimensions": 1536
        }]
      }
    }
  }
}
EOF

URI="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.DocumentDB/databaseAccounts/$COSMOS_ACCOUNT_NAME/sqlDatabases/$DATABASE_NAME/containers/${CONTAINER_NAME}?api-version=2024-05-15"

# Capability propagation can take up to 15 minutes.
# Retry with 30-second intervals for up to ~16 minutes.
MAX_RETRIES=32
RETRY_DELAY=30

echo "Waiting for EnableNoSQLVectorSearch capability to propagate..."
echo "(This may take several minutes on first deployment)"
echo ""

for i in $(seq 1 $MAX_RETRIES); do
    ELAPSED=$(( (i - 1) * RETRY_DELAY ))
    ELAPSED_MIN=$(( ELAPSED / 60 ))
    ELAPSED_SEC=$(( ELAPSED % 60 ))
    echo "  Attempt $i/$MAX_RETRIES (elapsed: ${ELAPSED_MIN}m${ELAPSED_SEC}s) ..."

    ERROR_OUTPUT=$(az rest --method put --uri "$URI" --body "@$BODY_FILE" 2>&1) && {
        echo ""
        echo "Container '$CONTAINER_NAME' created successfully!"
        exit 0
    }

    if echo "$ERROR_OUTPUT" | grep -q "capability has not been enabled"; then
        echo "    -> Capability not yet propagated. Retrying in ${RETRY_DELAY}s ..."
        sleep $RETRY_DELAY
    elif echo "$ERROR_OUTPUT" | grep -q "already exists"; then
        echo ""
        echo "Container '$CONTAINER_NAME' already exists."
        exit 0
    else
        echo "Unexpected error:"
        echo "$ERROR_OUTPUT"
        exit 1
    fi
done

TOTAL_MIN=$(( MAX_RETRIES * RETRY_DELAY / 60 ))
echo ""
echo "ERROR: Vector search capability did not propagate within ${TOTAL_MIN} minutes."
echo "Please wait a few more minutes and run: azd provision"
exit 1
