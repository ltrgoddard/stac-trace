#!/bin/bash

# Fetch STAC data from UP42 API
# Usage: ./fetch.sh [days] [host] [bbox]

set -euo pipefail

# Configuration with defaults
DAYS="${1:-7}"
HOST="${2:-oneatlas}"
BBOX="${3:-}"

# Load environment variables
set -a
source .env
set +a

# Validate credentials
if [[ -z "${UP42_USERNAME:-}" || -z "${UP42_PASSWORD:-}" ]]; then
    echo "Error: UP42_USERNAME and UP42_PASSWORD must be set in .env" >&2
    exit 1
fi

echo "Fetching STAC data from $HOST for last $DAYS days..." >&2

# Authenticate and get token
TOKEN=$(curl -s -X POST "https://auth.up42.com/realms/public/protocol/openid-connect/token" \
  -d "username=$UP42_USERNAME&password=$UP42_PASSWORD&grant_type=password&client_id=up42-api" \
  | jq -r '.access_token')

if [[ "$TOKEN" == "null" || -z "$TOKEN" ]]; then
    echo "Error: Authentication failed" >&2
    exit 1
fi

# Calculate date range (macOS compatible)
END_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_DATE=$(date -u -v-${DAYS}d +%Y-%m-%dT%H:%M:%SZ)

# Time-slicing for large date ranges (like Python version)
HOURS_PER_CHUNK=24  # 1 day chunks
TOTAL_HOURS=$((DAYS * 24))

if [[ $TOTAL_HOURS -gt 24 ]]; then
    echo "Large date range detected, using time-slicing..." >&2
    CURRENT_DATE="$START_DATE"

    # Collect all chunks
    {
        while [[ "$CURRENT_DATE" < "$END_DATE" ]]; do
            CHUNK_END=$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" -v+${HOURS_PER_CHUNK}H "$CURRENT_DATE" +%Y-%m-%dT%H:%M:%SZ)

            # Don't exceed end date
            if [[ "$CHUNK_END" > "$END_DATE" ]]; then
                CHUNK_END="$END_DATE"
            fi

            echo "  Fetching $CURRENT_DATE to $CHUNK_END..." >&2

            # Build search payload for this chunk
            PAYLOAD="{\"datetime\":\"$CURRENT_DATE/$CHUNK_END\",\"limit\":500}"
            if [[ -n "$BBOX" ]]; then
              PAYLOAD="${PAYLOAD%,*}","bbox\":[$BBOX]}"
            fi

            # Fetch chunk
            curl -s -H "Authorization: Bearer $TOKEN" \
              -H "Content-Type: application/json" \
              "https://api.up42.com/catalog/hosts/$HOST/stac/search" \
              -d "$PAYLOAD"

            CURRENT_DATE="$CHUNK_END"

            # Don't overwhelm the API
            sleep 0.5
        done
    } | jq -s '{
        type: "FeatureCollection",
        features: [ .[].features[] ]
    }'
else
    # Single request for small ranges
    PAYLOAD="{\"datetime\":\"$START_DATE/$END_DATE\",\"limit\":500}"
    if [[ -n "$BBOX" ]]; then
      PAYLOAD="${PAYLOAD%,*}","bbox\":[$BBOX]}"
    fi

    curl -s -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      "https://api.up42.com/catalog/hosts/$HOST/stac/search" \
      -d "$PAYLOAD"
fi