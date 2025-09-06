# stac-trace

Minimal tool for exploring [STAC catalogues](https://stacspec.org/en). Ultimate purpose: surfacing interesting locations that other people have tasked high-resolution satellite imagery of in recent months. 'What's being watched?' Start with a shell script-based command-line tool, then we'll expand into a Mapbox map later on.

## System Architecture

- Shell scripts (`fetch.sh`, `stac-trace`) for data fetching and orchestration
- DuckDB SQL (`cluster.sql`) for spatial processing and hotspot detection
- Makefile for pipeline orchestration
- Uses UP42 [API docs](https://developer.up42.com/reference/overview) for STAC queries
- UP42 credentials in `.env` (OAuth authentication, not project API keys)

## Key Technical Details

### Authentication
- Uses OAuth token endpoint: `https://auth.up42.com/realms/public/protocol/openid-connect/token`
- Client ID: `up42-api`
- Grant type: `password`
- Credentials from environment variables: `UP42_USERNAME` and `UP42_PASSWORD`

### API Limitations & Solutions
- **500-item limit per request**: Implemented automatic time-slicing in `fetch.sh`
- **Rate limiting**: Exponential backoff for geocoding requests
- **Collections endpoint**: Use `/collections` not `/catalog/collections`

### Satellite Filtering
- Filters to high-resolution (≤0.75m) satellites to exclude wide-area coverage (SPOT, Sentinel, etc.)
- Taskable collections filtered in DuckDB SQL queries
- This focuses on actual surveillance activity, not routine Earth observation

### Hotspot Detection Algorithm
1. Intersection-based clustering using spatial relationships
2. Groups images that intersect/overlap with each other
3. Uses connected components to find clusters of mutually intersecting images
4. Minimum threshold of 5 items per hotspot
5. Returns top locations with geocoded names

### Location Intelligence
- Reverse geocoding via OpenStreetMap Nominatim (no API key needed)
- Caches results in memory to avoid rate limits
- Falls back to coordinates if geocoding fails

### Google Earth Integration
- Generates direct URLs for each hotspot
- Format: `https://earth.google.com/web/@{lat},{lon},0a,50000d,35y,0h,0t,0r`
- 50km altitude for good regional context

## Important Implementation Notes

- **Date handling**: Handle both "Z" and "+00:00" timezone formats
- **Collection names**: Check both `constellation` and `collection` properties
- **Geocoding**: Use `geometryCentroid` from provider properties, fallback to bbox center
- **Error handling**: Always check response status codes and handle gracefully
- **Terminal output**: Simple shell output with emojis for clarity

## Common Issues & Solutions

1. **Authentication errors (404)**: Make sure to use OAuth, not project API keys
2. **Missing hotspots**: Check if API limit was hit (500 items) - deep search handles this
3. **Non-deterministic results**: Fixed by sorting locations before clustering
4. **Boundary splitting**: Fixed with adjacent cell merging in clustering algorithm
5. **Rate limiting on geocoding**: Implemented caching and exponential backoff