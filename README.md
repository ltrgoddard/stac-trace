# stac-trace

A command-line tool for exploring STAC (SpatioTemporal Asset Catalog) catalogues to discover what locations are being watched by satellites. Surface interesting surveillance patterns and hotspots of activity.

## Purpose

"What's being watched?" - This tool reveals where expensive satellite imagery is being tasked, exposing geopolitical hotspots, military movements, infrastructure monitoring, and areas of strategic interest.

## Features

- 🛰️ **Multi-provider search** - Query satellite imagery from OnAtlas, Maxar, Capella, and more
- 🎯 **Taskable satellites only** - Filters to high-resolution (≤0.75m) satellites that can be specifically tasked
- 📍 **Location intelligence** - Automatic reverse geocoding shows human-readable place names
- 🔥 **Hotspot detection** - Find the most surveilled locations worldwide
- 📈 **Temporal analysis** - Track surveillance patterns over time
- 🚀 **No API limits** - Automatically bypasses provider limits with smart time-slicing
- 🗺️ **Global coverage** - Search anywhere from local to planetary scale

## Installation

Requires Python 3.8+ and uses `uv` for dependency management:

```bash
# Clone the repository
git clone https://github.com/yourusername/stac-trace.git
cd stac-trace

# Install dependencies with uv
uv sync

# Set up credentials in .env file
cp .env.example .env
# Edit .env with your UP42 credentials
```

## Setup

Create a `.env` file with your UP42 credentials:

```env
UP42_USERNAME=your.email@example.com
UP42_PASSWORD=your_password_here
```

Get credentials at [UP42](https://up42.com) - free tier available.

## Usage

### List Available Satellite Collections

```bash
./stac-trace collections
```

Shows all available satellite collections with resolution and provider info.

### Search for Recent Imagery

```bash
# Search a specific area (NYC) for the last 30 days
./stac-trace search --bbox "-74.1,40.7,-73.9,40.8" --days 30

# Search with cloud coverage filter
./stac-trace search --bbox "-74.1,40.7,-73.9,40.8" --cloud 20

# Search different providers
./stac-trace search --host maxar --bbox "-77.1,38.85,-77,38.95" --days 7
```

### Find Surveillance Hotspots

The key feature - discovers locations with unusual surveillance activity:

```bash
# Find global hotspots from the last week
./stac-trace hotspots --days 7

# Analyze specific region (Middle East)
./stac-trace hotspots --bbox "30,-10,60,40" --days 14

# Check different satellite providers
./stac-trace hotspots --host maxar --days 30
```

Example output:
```
Top Hotspots:
• Rostov Oblast, Russia (47.0, 39.0): 29 images
• Makiivka Municipality, Ukraine (48.0, 38.0): 19 images
• Zaporizhia Oblast, Ukraine (47.0, 37.0): 18 images
```

### Watch a Specific Location

Track what's been watching a particular place:

```bash
# Check surveillance of Manhattan
./stac-trace watch --lat 40.7128 --lon -74.0060 --days 30

# Monitor with larger radius
./stac-trace watch --lat 50.45 --lon 30.52 --radius 0.5 --days 14
```

## Command Reference

### `collections`
List available satellite collections with metadata.
- Default: Shows only high-resolution taskable satellites (≤0.75m)
- `--all`: Show all available collections including wide-area satellites

### `search`
Search for satellite imagery with filters:
- `--host`: Provider to search (oneatlas, maxar, capellaspace, etc.)
- `--bbox`: Bounding box as "min_lon,min_lat,max_lon,max_lat"
- `--days`: Number of days to look back
- `--collection`: Specific collection to search
- `--cloud`: Maximum cloud coverage percentage
- `--limit`: Maximum results to return
- `--format`: Output format (table or json)

### `hotspots`
Find locations with high surveillance activity:
- `--host`: Provider to analyze
- `--days`: Number of days to analyze (automatically handles API limits)
- `--bbox`: Limit analysis to geographic region

### `watch`
Check surveillance history of a specific location:
- `--lat`: Latitude of location
- `--lon`: Longitude of location  
- `--host`: Provider to check
- `--radius`: Search radius in degrees (default 0.1°)
- `--days`: Historical period to check

## How It Works

1. **STAC Integration** - Uses the STAC (SpatioTemporal Asset Catalog) API standard to query multiple providers
2. **Smart Filtering** - Focuses on high-resolution taskable satellites (≤0.75m) to identify intentional surveillance
3. **Smart Pagination** - Automatically time-slices searches to bypass API limits (500 items/request)
4. **Location Intelligence** - Uses OpenStreetMap's Nominatim for reverse geocoding
5. **Pattern Detection** - Aggregates imagery by location grid to identify surveillance patterns

## Examples

### Finding Conflict Zones
```bash
# Ukraine/Russia border region
./stac-trace hotspots --bbox "30,45,40,55" --days 30

# Middle East surveillance
./stac-trace hotspots --bbox "30,20,50,40" --days 14

# Taiwan Strait activity  
./stac-trace hotspots --bbox "118,22,122,26" --days 7
```

### Infrastructure Monitoring
```bash
# Check DC government area
./stac-trace watch --lat 38.8977 --lon -77.0365 --days 30

# Monitor major ports
./stac-trace search --bbox "-118.3,-118.1,33.7,33.8" --days 14  # LA Port
```

### Global Analysis
```bash
# Worldwide hotspots (may take a few minutes)
./stac-trace hotspots --days 30 --bbox "-180,-90,180,90"
```

## Technical Details

- **Language**: Python 3.8+
- **Dependencies**: requests, click, pystac-client, rich, python-dotenv
- **API**: UP42 STAC-compliant catalog API
- **Geocoding**: OpenStreetMap Nominatim (no API key needed)
- **Rate Limiting**: Automatic handling with exponential backoff

## Privacy & Ethics

This tool only accesses publicly available satellite catalog metadata - not the actual imagery. It reveals what areas are being photographed, not the content of the images. Use responsibly and in compliance with all applicable laws.

## Contributing

Contributions welcome! Please feel free to submit issues and pull requests.

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- Built on the [STAC specification](https://stacspec.org/)
- Satellite data from [UP42](https://up42.com) marketplace
- Location data from [OpenStreetMap](https://www.openstreetmap.org/)
