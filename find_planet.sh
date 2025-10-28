#!/bin/bash
set -euo pipefail

# Load environment
set -a
source .env
set +a

# Get token
TOKEN=$(curl -s -X POST "https://auth.up42.com/realms/public/protocol/openid-connect/token" \
  -d "username=$UP42_USERNAME&password=$UP42_PASSWORD&grant_type=password&client_id=up42-api" \
  | jq -r '.access_token')

if [[ "$TOKEN" == "null" || -z "$TOKEN" ]]; then
    echo "Error: Authentication failed"
    exit 1
fi

# Find Planet/SkySat collections
echo "Searching for Planet/SkySat collections..."
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.up42.com/collections?size=200" | jq -r '.data[] | select(.name | test("planet|skysat"; "i")) | "\(.name) - Host: \(.hostName) - Title: \(.title)"'
