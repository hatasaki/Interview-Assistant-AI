#!/bin/bash
set -e

echo "=== Updating Entra ID App Registration redirect URI (postprovision) ==="

AUTH_CLIENT_ID=$(azd env get-value AUTH_CLIENT_ID 2>/dev/null) || AUTH_CLIENT_ID=""
WEBAPP_URL=$(azd env get-value AZURE_WEBAPP_URL 2>/dev/null) || WEBAPP_URL=""

if [ -z "$AUTH_CLIENT_ID" ]; then
    echo "ERROR: AUTH_CLIENT_ID not found in environment."
    exit 1
fi

if [ -z "$WEBAPP_URL" ]; then
    echo "ERROR: AZURE_WEBAPP_URL not found in environment."
    exit 1
fi

REDIRECT_URI="${WEBAPP_URL}/.auth/login/aad/callback"
echo "Setting redirect URI: $REDIRECT_URI"

# Update the App Registration with the redirect URI
az ad app update \
    --id "$AUTH_CLIENT_ID" \
    --web-redirect-uris "$REDIRECT_URI" \
    --enable-id-token-issuance true

echo "=== Redirect URI updated successfully ==="

# Create the vector-enabled Cosmos DB container
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
"$SCRIPT_DIR/create-vector-container.sh"
