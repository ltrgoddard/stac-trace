#!/bin/bash
# Fetch Planet SkySat data from 30-120 days ago (to account for 30-day archive lag)

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

# Date range: 30-120 days ago (90 days of data)
END_DATE=$(date -u -v-30d +%Y-%m-%dT%H:%M:%SZ)
START_DATE=$(date -u -v-120d +%Y-%m-%dT%H:%M:%SZ)

echo "Fetching Planet SkySat data from $START_DATE to $END_DATE" >&2
echo "Time range: 90 days (30-120 days ago)" >&2

# We need to chunk this into smaller time periods due to 250 limit
# Let's do 15-day chunks
echo "Using time-slicing..." >&2

ALL_FEATURES=""

for i in {0..5}; do
    CHUNK_START=$(date -u -v-$((120-i*15))d +%Y-%m-%dT%H:%M:%SZ)
    CHUNK_END=$(date -u -v-$((120-(i+1)*15))d +%Y-%m-%dT%H:%M:%SZ)

    echo "  Chunk $((i+1))/6: $CHUNK_START to $CHUNK_END" >&2

    PAYLOAD="{\"datetime\":\"$CHUNK_START/$CHUNK_END\",\"limit\":250}"

    RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      "https://api.up42.com/catalog/hosts/planet/stac/search" \
      -d "$PAYLOAD")

    # Extract filtered features
    CHUNK_FEATURES=$(echo "$RESPONSE" | jq -r '.features // [] | map(select(
        (.properties.constellation | ascii_downcase) != "spot" and
        (.properties.resolution | tonumber) <= 0.75
    )) | @json')

    if [[ "$CHUNK_FEATURES" != "[]" && "$CHUNK_FEATURES" != "null" ]]; then
        if [[ -z "$ALL_FEATURES" ]]; then
            ALL_FEATURES="$CHUNK_FEATURES"
        else
            ALL_FEATURES=$(echo "[$ALL_FEATURES,$CHUNK_FEATURES]" | jq -s 'flatten')
        fi
        FEATURE_COUNT=$(echo "$CHUNK_FEATURES" | jq 'length')
        echo "    Found $FEATURE_COUNT images" >&2
    fi

    sleep 0.5
done

# Output final GeoJSON
echo "{\"type\": \"FeatureCollection\", \"features\": $ALL_FEATURES}"
TOTAL=$(echo "$ALL_FEATURES" | jq 'length')
echo "" >&2
echo "✅ Total: $TOTAL Planet SkySat images" >&2
