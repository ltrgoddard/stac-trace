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

# Get SkySat collection details
echo "SkySat collection details:"
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.up42.com/collections?size=200" | jq '.data[] | select(.name == "skysat")'

echo ""
echo ""
echo "Testing search for last 7 days (without filters)..."
# Calculate dates
END_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_DATE=$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)

# Simple search
PAYLOAD="{\"datetime\":\"$START_DATE/$END_DATE\",\"limit\":10}"

curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.up42.com/catalog/hosts/planet/stac/search" \
  -d "$PAYLOAD" | jq '{feature_count: .features | length, sample: .features[0] | {id: .properties.id, datetime: .properties.datetime, constellation: .properties.constellation, resolution: .properties.resolution} }'
