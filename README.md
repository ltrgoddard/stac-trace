# stac-trace

Discover surveillance hotspots from satellite imagery catalogs. Uses persistent DuckDB storage for incremental data collection over time.

## Quick Start

```bash
# Set up credentials
cp .env.example .env
# Edit .env with your UP42 credentials (free tier at up42.com)

# Initialize database (one-time)
make init

# Sync data and analyze
make
```

## Usage

```bash
make init              # One-time database setup
make sync              # Fetch new data from API
make analyze           # Generate hotspots (instant, no API calls)
make                   # Sync + analyze (default)
make status            # Show database statistics
make geocode           # Add location names to hotspots
```

### Configuration

```bash
make DAYS=30                    # Sync last 30 days
make sync DAYS=365              # Backfill a year of data
make analyze ANALYZE_DAYS=7     # Analyze only last week
make HOST=maxar                 # Use different provider
make GEOCODE=1                  # Sync + analyze + geocode
```

### View Results

```bash
open index.html                 # Interactive map
cat data/hotspots.geojson       # Raw data
```

## Architecture

```
API → sync.sh → stac.duckdb ← analyze.sh → hotspots.geojson
                    ↓
            (persistent, grows over time)
```

- **Incremental**: Only fetches new data since last sync
- **Deduplication**: Skips items already in database
- **Fast analysis**: Hotspot detection runs locally, no API calls
- **Scalable**: Accumulate months/years of data

## Requirements

- `duckdb` - Database engine
- `jq` - JSON processing
- `curl` - API requests

```bash
# macOS
brew install duckdb jq
```

## How It Works

1. **Sync** - Downloads STAC metadata from UP42 API, stores in DuckDB
2. **Filter** - Keeps only high-resolution (≤0.75m) taskable satellites
3. **Cluster** - Groups images by ~22km grid cells
4. **Output** - GeoJSON with hotspots (5+ images per cell)

## License

MIT
