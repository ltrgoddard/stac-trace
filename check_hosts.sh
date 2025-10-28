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

# List available hosts
echo "Available UP42 hosts:"
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.up42.com/catalog/hosts"
