#!/bin/bash
# Fetch Planet SkySat data from 30-60 days ago (to account for 30-day archive lag)

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
    echo "Error: Authentication failed" >&2
    exit 1
fi

# Date range: 30-60 days ago
END_DATE=$(date -u -v-30d +%Y-%m-%dT%H:%M:%SZ)
START_DATE=$(date -u -v-60d +%Y-%m-%dT%H:%M:%SZ)

echo "Fetching Planet SkySat data from $START_DATE to $END_DATE" >&2

# Search payload (Planet has max limit of 250)
PAYLOAD="{\"datetime\":\"$START_DATE/$END_DATE\",\"limit\":250}"

# Fetch data - first check raw response
RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  "https://api.up42.com/catalog/hosts/planet/stac/search" \
  -d "$PAYLOAD")

# Check if response has features
if echo "$RESPONSE" | jq -e '.features' > /dev/null 2>&1; then
    echo "$RESPONSE" | jq '{
        type: "FeatureCollection",
        features: .features | map(select(
            (.properties.constellation | ascii_downcase) != "spot" and
            (.properties.resolution | tonumber) <= 0.75
        ))
    }'
else
    echo "Error: No features in response" >&2
    echo "$RESPONSE" >&2
    echo '{"type":"FeatureCollection","features":[]}'
fi
