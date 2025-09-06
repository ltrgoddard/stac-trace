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
            PAYLOAD="{\"datetime\":\"$CURRENT_DATE/$CHUNK_END\",\"limit\":500,\"query\":{\"resolution\":{\"lte\":0.75}}}"
            if [[ -n "$BBOX" ]]; then
              PAYLOAD="${PAYLOAD%,*}","bbox\":[$BBOX]}"
            fi

            # Fetch all pages for this chunk
            ALL_FEATURES=""
            NEXT_PAYLOAD="$PAYLOAD"

            while true; do
                echo "    Fetching page..." >&2

                # Make the API call
                RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
                  -H "Content-Type: application/json" \
                  "https://api.up42.com/catalog/hosts/$HOST/stac/search" \
                  -d "$NEXT_PAYLOAD")

                # Extract features from this page
                PAGE_FEATURES=$(echo "$RESPONSE" | jq -r '.features // [] | @json')
                if [[ "$PAGE_FEATURES" != "[]" && "$PAGE_FEATURES" != "null" ]]; then
                    if [[ -z "$ALL_FEATURES" ]]; then
                        ALL_FEATURES="$PAGE_FEATURES"
                    else
                        # Merge features from this page
                        ALL_FEATURES=$(echo "[$ALL_FEATURES,$PAGE_FEATURES]" | jq -s 'flatten')
                    fi
                fi

                # Check if there are more pages
                NEXT_URL=$(echo "$RESPONSE" | jq -r '.links[]? | select(.rel == "next") | .href // empty')
                if [[ -z "$NEXT_URL" ]]; then
                    break
                fi

                # For next page, we need to construct the payload differently
                # UP42 uses token-based pagination
                NEXT_TOKEN=$(echo "$RESPONSE" | jq -r '.links[]? | select(.rel == "next") | .href | capture("token=(?<token>[^&]+)") | .token // empty')
                if [[ -n "$NEXT_TOKEN" ]]; then
                    NEXT_PAYLOAD=$(echo "$PAYLOAD" | jq ". + {\"token\": \"$NEXT_TOKEN\"}")
                else
                    break
                fi

                # Don't overwhelm the API
                sleep 0.5
            done

            # Output features for this chunk
            if [[ -n "$ALL_FEATURES" ]]; then
                echo "{\"features\": $ALL_FEATURES}"
            else
                echo "{\"features\": []}"
            fi

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
    PAYLOAD="{\"datetime\":\"$START_DATE/$END_DATE\",\"limit\":500,\"query\":{\"resolution\":{\"lte\":0.75}}}"
    if [[ -n "$BBOX" ]]; then
      PAYLOAD="${PAYLOAD%,*}","bbox\":[$BBOX]}"
    fi

    # For single requests, still check for pagination (though unlikely for small ranges)
    RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      "https://api.up42.com/catalog/hosts/$HOST/stac/search" \
      -d "$PAYLOAD")

    # Check if there are more pages
    NEXT_URL=$(echo "$RESPONSE" | jq -r '.links[]? | select(.rel == "next") | .href // empty')
    if [[ -n "$NEXT_URL" ]]; then
        echo "Warning: More than 500 results available, but pagination not fully implemented for single requests" >&2
    fi

    echo "$RESPONSE"
fi