# STAC-Trace: Persistent Satellite Imagery Hotspot Analysis
# Uses DuckDB for incremental data collection over time

.PHONY: all init sync analyze status clean help geocode

# Configuration
HOST ?= oneatlas
DAYS ?= 7
ANALYZE_DAYS ?=
GEOCODE ?= 0

# Paths
DATA_DIR = data
DB_PATH = $(DATA_DIR)/stac.duckdb
OUTPUT_FILE = $(DATA_DIR)/hotspots.geojson

# Default: sync new data and analyze
all: sync analyze
ifeq ($(GEOCODE),1)
	@$(MAKE) geocode
endif

# Create data directory
$(DATA_DIR):
	@mkdir -p $@

# Initialize database (one-time setup)
init: $(DATA_DIR)
	@chmod +x init.sh
	@./init.sh $(DB_PATH)

# Sync new data from API (incremental)
sync: $(DATA_DIR)
	@chmod +x sync.sh
	@echo "Syncing STAC data from $(HOST) for last $(DAYS) days..."
	@./sync.sh $(DAYS) $(HOST)

# Analyze database and generate hotspots
analyze: $(DATA_DIR)
	@chmod +x analyze.sh
ifdef ANALYZE_DAYS
	@./analyze.sh $(ANALYZE_DAYS) $(OUTPUT_FILE)
else
	@./analyze.sh "" $(OUTPUT_FILE)
endif

# Show database status
status:
	@chmod +x status.sh
	@./status.sh

# Add location names via reverse geocoding
geocode: $(OUTPUT_FILE)
	@echo "Geocoding hotspot locations..."
	@chmod +x geocode.sh
	@./geocode.sh $(OUTPUT_FILE) $(OUTPUT_FILE)
	@echo "Added location names to hotspots"

# Backfill historical data (fetch more days)
backfill:
	@echo "Backfilling historical data ($(DAYS) days)..."
	@chmod +x sync.sh
	@./sync.sh $(DAYS) $(HOST)

# Clean generated files (keeps database)
clean:
	@echo "Cleaning output files..."
	@rm -f $(OUTPUT_FILE)

# Reset everything (removes database)
reset:
	@echo "Resetting database..."
	@rm -rf $(DATA_DIR)
	@mkdir -p $(DATA_DIR)

# Install dependencies
install:
	@echo "Checking dependencies..."
	@which duckdb || (echo "Please install DuckDB: https://duckdb.org/docs/installation/" && exit 1)
	@which jq || (echo "Please install jq: brew install jq" && exit 1)
	@which curl || (echo "Please install curl" && exit 1)
	@echo "All dependencies installed."

# Show help
help:
	@echo "STAC-Trace: Satellite Imagery Hotspot Analysis"
	@echo ""
	@echo "Quick Start:"
	@echo "  make init          # One-time database setup"
	@echo "  make sync          # Fetch new data from API"
	@echo "  make analyze       # Generate hotspots from database"
	@echo "  make               # Sync + analyze (default)"
	@echo ""
	@echo "Other Commands:"
	@echo "  make status        # Show database statistics"
	@echo "  make geocode       # Add location names to hotspots"
	@echo "  make backfill DAYS=365  # Fetch historical data"
	@echo "  make clean         # Remove output files"
	@echo "  make reset         # Delete database and start fresh"
	@echo ""
	@echo "Configuration:"
	@echo "  HOST=oneatlas      # STAC host (default: oneatlas)"
	@echo "  DAYS=7             # Days to sync (default: 7)"
	@echo "  ANALYZE_DAYS=30    # Days to analyze (default: all)"
	@echo "  GEOCODE=1          # Enable geocoding"
	@echo ""
	@echo "Examples:"
	@echo "  make DAYS=30                    # Sync last 30 days"
	@echo "  make sync DAYS=365              # Backfill a year"
	@echo "  make analyze ANALYZE_DAYS=7     # Analyze last week only"
	@echo "  make GEOCODE=1                  # Sync + analyze + geocode"
	@echo ""
	@echo "Workflow:"
	@echo "  1. make init       # First time only"
	@echo "  2. make sync       # Run daily via cron"
	@echo "  3. make analyze    # Generate hotspots anytime (instant)"
