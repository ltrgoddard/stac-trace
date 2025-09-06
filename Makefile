# STAC Hotspots Analysis Pipeline
# Uses DuckDB spatial extension for minimal, efficient processing

.PHONY: all clean help install test

# Configuration
HOST ?= oneatlas
DAYS ?= 7
BBOX ?=
TOP_N ?= 10

# File targets
DATA_DIR = data
DATA_FILE = $(DATA_DIR)/stac_data_$(shell date +%Y%m%d_%H%M%S).json
OUTPUT_FILE = $(DATA_DIR)/hotspots.geojson

# Default target
all: $(DATA_DIR) $(OUTPUT_FILE)

# Create data directory
$(DATA_DIR):
	@mkdir -p $@

# Make scripts executable
fetch.sh cluster.sql:
	chmod +x fetch.sh

# Fetch STAC data
$(DATA_FILE): fetch.sh
	@echo "📡 Fetching STAC data from $(HOST) for last $(DAYS) days..."
	@./fetch.sh $(DAYS) $(HOST) "$(BBOX)" > $@

# Process hotspots with DuckDB
$(OUTPUT_FILE): $(DATA_FILE) cluster.sql
	@echo "🔍 Processing hotspots with DuckDB..."
	@sed "s|DATA_FILE_PLACEHOLDER|$<|g" cluster.sql | duckdb -json | jq '.[0].geojson' > $@
	@echo "✅ Generated hotspots.geojson with top $(TOP_N) hotspots"

# Install dependencies
install:
	@echo "📦 Installing dependencies..."
	uv add duckdb
	@echo "🔧 Installing DuckDB CLI..."
	which duckdb || (echo "Please install DuckDB: https://duckdb.org/docs/installation/" && exit 1)

# Test the pipeline
test: $(DATA_FILE)
	@echo "🧪 Testing pipeline..."
	@echo "Data file size: $$(wc -c < $<) bytes"
	@echo "Number of features: $$(cat $< | jq '.features | length')"
	@echo "Sample feature:"
	@cat $< | jq '.features[0] | {id: .properties.id, datetime: .properties.datetime, collection: .properties.constellation}'

# Clean up generated files
clean:
	@echo "🧹 Cleaning up..."
	rm -rf $(DATA_DIR)/*
	@mkdir -p $(DATA_DIR)

# Show help
help:
	@echo "STAC Hotspots Analysis Pipeline"
	@echo ""
	@echo "Targets:"
	@echo "  all       - Run full pipeline (default)"
	@echo "  install   - Install dependencies"
	@echo "  test      - Test pipeline with sample data"
	@echo "  clean     - Remove generated files"
	@echo ""
	@echo "Variables:"
	@echo "  HOST      - STAC host (default: oneatlas)"
	@echo "  DAYS      - Days to look back (default: 7)"
	@echo "  BBOX      - Bounding box (optional)"
	@echo "  TOP_N     - Number of top hotspots (default: 10)"
	@echo ""
	@echo "Examples:"
	@echo "  make HOST=capella DAYS=30"
	@echo "  make BBOX='-122.5,37.5,-122.0,38.0'"
	@echo "  make test"

# Show current configuration
config:
	@echo "Current configuration:"
	@echo "  HOST: $(HOST)"
	@echo "  DAYS: $(DAYS)"
	@echo "  BBOX: $(BBOX)"
	@echo "  TOP_N: $(TOP_N)"
	@echo ""
	@echo "Note: Time-slicing automatically enabled for DAYS > 1"
	@echo "This bypasses the 500-item API limit for comprehensive analysis"