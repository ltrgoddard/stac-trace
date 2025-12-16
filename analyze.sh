#!/bin/bash

# Analyze STAC database and generate hotspots GeoJSON
# Usage: ./analyze.sh [days] [output_file]

set -euo pipefail

DAYS="${1:-}"  # Empty means all data
OUTPUT="${2:-data/hotspots.geojson}"
DB_PATH="${DB_PATH:-data/stac.duckdb}"

# Check database exists
if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: Database not found at $DB_PATH. Run 'make init && make sync' first." >&2
    exit 1
fi

# Check if database has items
ITEM_COUNT=$(duckdb "$DB_PATH" -noheader -csv -c "SELECT COUNT(*) FROM items;")
if [[ "$ITEM_COUNT" -eq 0 ]]; then
    echo "Error: No items in database. Run 'make sync' first." >&2
    exit 1
fi

# Build date filter
if [[ -n "$DAYS" ]]; then
    CUTOFF_DATE=$(date -u -v-${DAYS}d +%Y-%m-%dT%H:%M:%SZ)
    DATE_FILTER="(properties->>'datetime')::TIMESTAMP >= '$CUTOFF_DATE'::TIMESTAMP"
    echo "Analyzing items from last $DAYS days..."
else
    DATE_FILTER="1=1"  # No filter, use all data
    echo "Analyzing all items in database..."
fi

# Run analysis
echo "Running hotspot detection..."

# Replace placeholder and execute
sed "s|DATE_FILTER_PLACEHOLDER|$DATE_FILTER|g" analyze.sql \
    | duckdb "$DB_PATH" -json \
    | jq '.[0].geojson' > "$OUTPUT"

# Report results
HOTSPOT_COUNT=$(jq '.features | length' "$OUTPUT" 2>/dev/null || echo "0")
TOTAL_IMAGES=$(jq '[.features[].properties.hotspot_image_count] | add // 0' "$OUTPUT" 2>/dev/null || echo "0")

echo ""
echo "Analysis complete:"
echo "  Items analyzed: $ITEM_COUNT"
echo "  Hotspots found: $HOTSPOT_COUNT"
echo "  Images in hotspots: $TOTAL_IMAGES"
echo "  Output: $OUTPUT"

if [[ "$HOTSPOT_COUNT" -gt 0 ]]; then
    echo ""
    echo "Top hotspots:"
    jq -r '.features | sort_by(-.properties.hotspot_image_count) | .[0:10] | .[] | "  \(.properties.hotspot_image_count) images: (\(.properties.hotspot_centroid_lat | tostring[0:7]), \(.properties.hotspot_centroid_lon | tostring[0:7])) [\(.properties.primary_collection)]"' "$OUTPUT" 2>/dev/null || true
fi
