#!/bin/bash

# Show database status and statistics
# Usage: ./status.sh

set -euo pipefail

DB_PATH="${DB_PATH:-data/stac.duckdb}"

# Check database exists
if [[ ! -f "$DB_PATH" ]]; then
    echo "Database not found at $DB_PATH"
    echo "Run 'make init' to create it."
    exit 0
fi

echo "STAC Database Status"
echo "===================="
echo ""

# Database file size
DB_SIZE=$(ls -lh "$DB_PATH" | awk '{print $5}')
echo "Database: $DB_PATH ($DB_SIZE)"
echo ""

# Item counts
echo "Items:"
duckdb "$DB_PATH" <<'SQL'
SELECT
    COUNT(*) as total_items,
    COUNT(DISTINCT host) as hosts,
    MIN((properties->>'datetime')::TIMESTAMP) as earliest,
    MAX((properties->>'datetime')::TIMESTAMP) as latest
FROM items;
SQL

echo ""
echo "Items by host:"
duckdb "$DB_PATH" -c "SELECT host, COUNT(*) as items FROM items GROUP BY host ORDER BY items DESC;"

echo ""
echo "Items by constellation:"
duckdb "$DB_PATH" -c "
SELECT
    properties->>'constellation' as constellation,
    COUNT(*) as items
FROM items
GROUP BY constellation
ORDER BY items DESC
LIMIT 10;
"

echo ""
echo "Recent syncs:"
duckdb "$DB_PATH" -c "
SELECT
    synced_at,
    host,
    region,
    items_added,
    start_date::DATE || ' to ' || end_date::DATE as date_range
FROM sync_log
ORDER BY synced_at DESC
LIMIT 10;
"

echo ""
echo "Items by month:"
duckdb "$DB_PATH" -c "
SELECT
    strftime((properties->>'datetime')::TIMESTAMP, '%Y-%m') as month,
    COUNT(*) as items
FROM items
GROUP BY month
ORDER BY month DESC
LIMIT 12;
"
