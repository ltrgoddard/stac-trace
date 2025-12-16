# stac-trace

Minimal tool for exploring [STAC catalogues](https://stacspec.org/en). Ultimate purpose: surfacing interesting locations that other people have tasked high-resolution satellite imagery of in recent months. 'What's being watched?'

## System Architecture

- **Shell scripts** (`scripts/`) for data fetching, analysis, and utilities
- **DuckDB SQL** (`queries/analyze.sql`) for spatial processing and hotspot detection
- **Makefile** for pipeline orchestration
- **Persistent DuckDB database** at `data/stac.duckdb` for incremental data collection
- Uses UP42 [API docs](https://developer.up42.com/reference/overview) for STAC queries
- UP42 credentials in `.env` (OAuth authentication, not project API keys)

## Directory Structure

```
scripts/
  init.sh      # Database initialization
  sync.sh      # Incremental data fetch from API
  analyze.sh   # Run hotspot detection
  geocode.sh   # Reverse geocode hotspot locations
  status.sh    # Show database statistics
queries/
  analyze.sql  # DuckDB SQL for hotspot detection
data/
  stac.duckdb       # Persistent database
  hotspots.geojson  # Analysis output
```

## Workflow

```bash
make init              # One-time database setup
make sync DAYS=30      # Fetch last 30 days of data
make analyze           # Generate hotspots (instant, runs on DB)
make status            # Show database statistics
make GEOCODE=1         # Sync + analyze + geocode in one step
```

## Key Technical Details

### Authentication
- Uses OAuth token endpoint: `https://auth.up42.com/realms/public/protocol/openid-connect/token`
- Client ID: `up42-api`
- Grant type: `password`
- Credentials from environment variables: `UP42_USERNAME` and `UP42_PASSWORD`

### API Limitations & Solutions
- **500-item limit per request**: Pagination with `next` token
- **Global coverage**: Splits world into 5 regions (Americas, Europe/Africa, Middle East/Asia, East Asia/Pacific, Antarctica) to ensure complete coverage
- **Rate limiting**: 0.3s delay between paginated requests

### Satellite Filtering
- Filters to high-resolution (≤0.75m GSD) satellites
- Excludes SPOT constellation (wide-area coverage)
- Filtering applied both during fetch (jq) and in SQL queries
- Focuses on actual tasking activity, not routine Earth observation

### Hotspot Detection Algorithm
1. **Grid-based clustering**: Uses 0.1 degree (~11km) grid cells
2. **Adjacent cell merging**: Groups 2x2 grid cells to avoid boundary splitting
3. **Minimum threshold**: 5 images per hotspot
4. **Convex hull**: Creates polygon encompassing all images in cluster
5. **Outputs**: GeoJSON FeatureCollection with centroid, image count, date range

### Database Schema

```sql
-- Raw STAC items (append-only, deduplicated by id)
items (id TEXT PRIMARY KEY, geometry JSON, properties JSON, bbox JSON, host TEXT, fetched_at TIMESTAMP)

-- Sync tracking for incremental fetches
sync_log (id INTEGER, host TEXT, region TEXT, start_date TIMESTAMP, end_date TIMESTAMP, items_added INTEGER, synced_at TIMESTAMP)
```

### Location Intelligence
- Reverse geocoding via OpenStreetMap Nominatim (no API key needed)
- Respects rate limits: 1 request per second
- Simplifies names to first 2-3 address components
- Falls back to coordinates if geocoding fails

## Common Issues & Solutions

1. **Authentication errors (404)**: Make sure to use OAuth, not project API keys
2. **Database not found**: Run `make init` first
3. **No items**: Check API credentials, run `make sync`
4. **Boundary splitting**: Fixed by 2x2 grid cell merging in clustering algorithm
5. **Rate limiting on geocoding**: 1.1s delay between requests per Nominatim policy
