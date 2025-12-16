#!/bin/bash

# Initialize DuckDB database with schema
# Usage: ./init.sh [database_path]

set -euo pipefail

DB_PATH="${1:-data/stac.duckdb}"
DATA_DIR=$(dirname "$DB_PATH")

echo "Initializing STAC database at $DB_PATH..."

# Create data directory if needed
mkdir -p "$DATA_DIR"

# Remove existing database if it exists
if [[ -f "$DB_PATH" ]]; then
    echo "Removing existing database..."
    rm -f "$DB_PATH"
fi

# Create database with schema
duckdb "$DB_PATH" <<'SQL'
-- Install and load spatial extension
INSTALL spatial;
LOAD spatial;

-- Raw STAC items (append-only, deduplicated by id)
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    geometry JSON,
    properties JSON,
    bbox JSON,
    host TEXT,
    fetched_at TIMESTAMP DEFAULT now()
);

-- Sync tracking for incremental fetches
CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY,
    host TEXT,
    region TEXT,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    items_added INTEGER,
    synced_at TIMESTAMP DEFAULT now()
);

-- Create sequence for sync_log
CREATE SEQUENCE sync_log_seq START 1;
SQL

echo "Database initialized with schema:"
duckdb "$DB_PATH" -c "DESCRIBE items;"
echo ""
duckdb "$DB_PATH" -c "DESCRIBE sync_log;"
echo ""
echo "Done. Run 'make sync' to fetch data."
