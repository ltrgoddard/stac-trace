#!/bin/bash

# Incremental sync of STAC data to DuckDB
# Usage: ./sync.sh [days] [host]

set -euo pipefail

DAYS="${1:-7}"
HOST="${2:-oneatlas}"
DB_PATH="${DB_PATH:-data/stac.duckdb}"

# Load environment variables
set -a
source .env
set +a

# Validate credentials
if [[ -z "${UP42_USERNAME:-}" || -z "${UP42_PASSWORD:-}" ]]; then
    echo "Error: UP42_USERNAME and UP42_PASSWORD must be set in .env" >&2
    exit 1
fi

# Check database exists
if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: Database not found at $DB_PATH. Run 'make init' first." >&2
    exit 1
fi

echo "Syncing STAC data from $HOST for last $DAYS days..."

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

# Temporary file for batch inserts
TEMP_FILE=$(mktemp)
trap "rm -f $TEMP_FILE" EXIT

TOTAL_NEW=0

# Function to fetch a single region with pagination
fetch_region() {
    local REGION_BBOX="$1"
    local REGION_NAME="$2"

    echo "  Fetching $REGION_NAME..." >&2

    PAYLOAD="{\"datetime\":\"$START_DATE/$END_DATE\",\"limit\":500,\"bbox\":[$REGION_BBOX]}"
    NEXT_PAYLOAD="$PAYLOAD"
    PAGE_COUNT=0
    REGION_ITEMS=0

    while true; do
        PAGE_COUNT=$((PAGE_COUNT + 1))

        # Make the API call
        RESPONSE=$(curl -s -H "Authorization: Bearer $TOKEN" \
          -H "Content-Type: application/json" \
          "https://api.up42.com/catalog/hosts/$HOST/stac/search" \
          -d "$NEXT_PAYLOAD")

        # Extract features (filtering SPOT and low-res)
        FEATURES=$(echo "$RESPONSE" | jq -c '.features // [] | .[] | select(
            (.properties.constellation | ascii_downcase) != "spot" and
            (.properties.resolution | tonumber) <= 0.75
        )')

        # Process each feature
        while IFS= read -r feature; do
            [[ -z "$feature" ]] && continue

            ID=$(echo "$feature" | jq -r '.properties.id')
            GEOMETRY=$(echo "$feature" | jq -c '.geometry')
            PROPERTIES=$(echo "$feature" | jq -c '.properties')
            BBOX=$(echo "$feature" | jq -c '.bbox')

            # Write to temp file for batch insert
            echo "$ID	$GEOMETRY	$PROPERTIES	$BBOX	$HOST" >> "$TEMP_FILE"
            REGION_ITEMS=$((REGION_ITEMS + 1))
        done <<< "$FEATURES"

        # Check if there are more pages
        NEXT_TOKEN=$(echo "$RESPONSE" | jq -r '.links[]? | select(.rel == "next") | .href | capture("next=(?<next>[^&]+)") | .next // empty')
        if [[ -z "$NEXT_TOKEN" ]]; then
            break
        fi

        NEXT_PAYLOAD=$(echo "$PAYLOAD" | jq ". + {\"next\": \"$NEXT_TOKEN\"}")
        sleep 0.3
    done

    echo "    $REGION_NAME: $REGION_ITEMS items ($PAGE_COUNT pages)" >&2

    # Log this sync
    duckdb "$DB_PATH" -c "
        INSERT INTO sync_log (id, host, region, start_date, end_date, items_added)
        VALUES (nextval('sync_log_seq'), '$HOST', '$REGION_NAME', '$START_DATE', '$END_DATE', $REGION_ITEMS);
    "

    echo "$REGION_ITEMS"
}

echo "Querying regions..."

# Fetch all regions (simple approach avoids bash associative array issues)
for region_spec in \
    "Americas:-180,-60,-60,75" \
    "Europe_Africa:-30,-60,60,75" \
    "Middle_East_Asia:30,-60,90,75" \
    "East_Asia_Pacific:60,-60,180,75" \
    "Antarctica:-180,-90,180,-60"
do
    REGION_NAME="${region_spec%%:*}"
    REGION_BBOX="${region_spec#*:}"
    ITEMS=$(fetch_region "$REGION_BBOX" "$REGION_NAME")
    TOTAL_NEW=$((TOTAL_NEW + ITEMS))
done

# Bulk insert into database (ignore duplicates)
if [[ -s "$TEMP_FILE" ]]; then
    echo ""
    echo "Inserting items into database..."

    BEFORE_COUNT=$(duckdb "$DB_PATH" -noheader -csv -c "SELECT COUNT(*) FROM items;")

    duckdb "$DB_PATH" <<SQL
-- Create temp table for import
CREATE TEMP TABLE temp_items (
    id TEXT,
    geometry TEXT,
    properties TEXT,
    bbox TEXT,
    host TEXT
);

-- Import from TSV
COPY temp_items FROM '$TEMP_FILE' (DELIMITER '\t');

-- Insert new items (ignore duplicates)
INSERT OR IGNORE INTO items (id, geometry, properties, bbox, host)
SELECT id, geometry::JSON, properties::JSON, bbox::JSON, host
FROM temp_items;

DROP TABLE temp_items;
SQL

    AFTER_COUNT=$(duckdb "$DB_PATH" -noheader -csv -c "SELECT COUNT(*) FROM items;")
    NEW_INSERTED=$((AFTER_COUNT - BEFORE_COUNT))

    echo "Inserted $NEW_INSERTED new items (skipped $((TOTAL_NEW - NEW_INSERTED)) duplicates)"
else
    echo "No new items found"
fi

echo ""
echo "Sync complete. Database: $DB_PATH"
duckdb "$DB_PATH" -c "SELECT COUNT(*) as total_items FROM items;"
