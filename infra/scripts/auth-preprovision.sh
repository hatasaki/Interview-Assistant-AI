#!/bin/bash
set -e

echo "=== Entra ID App Registration (preprovision) ==="

# Check if AUTH_CLIENT_ID already has a value
EXISTING_CLIENT_ID=$(azd env get-value AUTH_CLIENT_ID 2>/dev/null) || EXISTING_CLIENT_ID=""
if [ -n "$EXISTING_CLIENT_ID" ]; then
    echo "Entra ID App Registration already configured: $EXISTING_CLIENT_ID"

    # Ensure a client secret exists
    EXISTING_SECRET=$(azd env get-value AUTH_CLIENT_SECRET 2>/dev/null) || EXISTING_SECRET=""
    if [ -n "$EXISTING_SECRET" ]; then
        echo "Client secret already configured. Skipping."
        exit 0
    fi
    echo "Client secret not found. Creating a new one..."
    APP_ID="$EXISTING_CLIENT_ID"
else
    APP_DISPLAY_NAME="interview-assistant-ai-${AZURE_ENV_NAME}"

    # Check if app registration already exists by display name
    APP_ID=$(az ad app list --display-name "$APP_DISPLAY_NAME" --query "[0].appId" -o tsv 2>/dev/null || echo "")

    if [ -n "$APP_ID" ] && [ "$APP_ID" != "None" ]; then
        echo "Found existing App Registration: $APP_ID"
    else
        echo "Creating Entra ID App Registration: $APP_DISPLAY_NAME"
        APP_ID=$(az ad app create \
            --display-name "$APP_DISPLAY_NAME" \
            --sign-in-audience AzureADMyOrg \
            --enable-id-token-issuance true \
            --query "appId" -o tsv)
        echo "Created App Registration: $APP_ID"
    fi

    azd env set AUTH_CLIENT_ID "$APP_ID"
fi

# Create a new client secret
echo "Creating client secret..."
SECRET=$(az ad app credential reset \
    --id "$APP_ID" \
    --display-name "azd-managed" \
    --years 2 \
    --query "password" -o tsv)

azd env set AUTH_CLIENT_SECRET "$SECRET"

echo "=== Entra ID App Registration configured successfully ==="
