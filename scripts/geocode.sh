#!/bin/bash

# Add reverse geocoding to hotspots.geojson using OpenStreetMap Nominatim
# Usage: ./geocode.sh [input_file] [output_file]

set -euo pipefail

INPUT_FILE="${1:-data/hotspots.geojson}"
OUTPUT_FILE="${2:-data/hotspots.geojson}"

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Error: Input file $INPUT_FILE not found" >&2
    exit 1
fi

echo "Geocoding hotspots..." >&2

# Process each feature and add location_name
TEMP_FILE=$(mktemp)
FEATURES_FILE=$(mktemp)

# Extract features to a temp file first (to avoid pipe subshell issues)
jq -c '.features[]' "$INPUT_FILE" > "$FEATURES_FILE"

# Process each feature
while IFS= read -r feature; do
    lat=$(echo "$feature" | jq -r '.properties.hotspot_centroid_lat // empty')
    lon=$(echo "$feature" | jq -r '.properties.hotspot_centroid_lon // empty')

    if [[ -n "$lat" && -n "$lon" ]]; then
        # Call Nominatim API with rate limiting
        response=$(curl -s --max-time 10 \
            -H "User-Agent: stac-trace/1.0 (satellite-hotspots)" \
            "https://nominatim.openstreetmap.org/reverse?lat=$lat&lon=$lon&format=json&zoom=10" \
            || echo "{}")

        location_name=$(echo "$response" | jq -r '.display_name // empty')

        # Rate limit: 1 request per second (Nominatim policy)
        sleep 1.1

        if [[ -n "$location_name" && "$location_name" != "null" ]]; then
            # Simplify the location name (take first 2-3 parts)
            short_name=$(echo "$location_name" | cut -d',' -f1-3 | sed 's/^ *//' | head -c 80)
            echo "  $short_name" >&2
            echo "$feature" | jq --arg name "$short_name" '.properties.location_name = $name' >> "$TEMP_FILE"
        else
            echo "  ($lat, $lon) - no address found" >&2
            # Create a simple coordinate-based name
            echo "$feature" | jq --arg name "($lat, $lon)" '.properties.location_name = $name' >> "$TEMP_FILE"
        fi
    else
        echo "$feature" >> "$TEMP_FILE"
    fi
done < "$FEATURES_FILE"

# Wrap features back into FeatureCollection
if [[ -s "$TEMP_FILE" ]]; then
    jq -s '{type: "FeatureCollection", features: .}' "$TEMP_FILE" > "$OUTPUT_FILE"
    COUNT=$(wc -l < "$TEMP_FILE" | tr -d ' ')
    echo "Geocoded $COUNT hotspots -> $OUTPUT_FILE" >&2
else
    cp "$INPUT_FILE" "$OUTPUT_FILE"
    echo "No hotspots to geocode" >&2
fi

rm -f "$TEMP_FILE" "$FEATURES_FILE"
