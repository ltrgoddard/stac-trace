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
- 🦆 **DuckDB Pipeline** - Ultra-minimal hotspots analysis with spatial processing

## Installation

Requires DuckDB and curl. No Python dependencies needed for the minimal version:

```bash
# Clone the repository
git clone https://github.com/yourusername/stac-trace.git
cd stac-trace

# Install DuckDB (if not already installed)
# macOS: brew install duckdb
# Linux: See https://duckdb.org/docs/installation/
# Windows: See https://duckdb.org/docs/installation/

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

The tool uses DuckDB for spatial processing and curl for API requests. No Python runtime required.

### Data Organization

All generated data files are stored in the `data/` directory to keep the main repository clean:
- `data/stac_data_*.json` - Raw STAC data from API
- `data/hotspots.geojson` - Processed hotspot results
- Use `make clean` to remove all generated files

## Usage

### Find Surveillance Hotspots

The key feature - discovers locations with unusual surveillance activity:

```bash
# Find global hotspots from the last week
./stac-trace 7

# Analyze specific region (Middle East) for 14 days
./stac-trace 14 oneatlas "30,-10,60,40"

# Check different satellite providers
make HOST=maxar DAYS=30 all
```

Example output generates `data/hotspots.geojson` with clustered surveillance locations.

### Manual Pipeline Control

For more control over the analysis:

```bash
# Custom parameters with Make
make HOST=capella DAYS=30 BBOX='-122.5,37.5,-122.0,38.0'

# Just fetch data without processing
make data/stac_data_$(date +%Y%m%d_%H%M%S).json

# Process existing data
make data/hotspots.geojson
```

## How the DuckDB Pipeline Works

The tool uses a minimal, efficient pipeline with DuckDB spatial processing:

1. **fetch.sh** - Downloads STAC data from UP42 API (with automatic time-slicing to bypass 500-item limits)
2. **cluster.sql** - Processes data with DuckDB spatial extension for hotspot detection
3. **Output** - GeoJSON FeatureCollection with clustered surveillance hotspots

### Pipeline Features
- ⚡ **Fast processing** - DuckDB columnar engine
- 🗺️ **Native spatial** - Built-in geospatial functions
- 📦 **Minimal deps** - Just DuckDB and curl
- 🔧 **Configurable** - Makefile with proper file targets
- 🚀 **No API limits** - Automatic time-slicing bypasses 500-item limit
- 📊 **Scalable** - Handles thousands of images efficiently

### Manual Usage

```bash
# Run the complete pipeline
make

# Custom parameters
make HOST=capella DAYS=30 BBOX='-122.5,37.5,-122.0,38.0'

# Just fetch data
./fetch.sh 7 oneatlas > stac_data.json

# Process with DuckDB
sed "s|DATA_FILE_PLACEHOLDER|stac_data.json|g" cluster.sql | duckdb -json
```
```

## Usage

### Simple Usage
```bash
# Find hotspots from last 7 days globally
./stac-trace

# Custom time period
./stac-trace 30

# Specific provider and region
./stac-trace 14 maxar "30,20,50,40"
```

### Advanced Usage with Make
```bash
# Full control with Make variables
make HOST=capella DAYS=30 BBOX='-122.5,37.5,-122.0,38.0'

# Install dependencies
make install

# Test pipeline
make test

# Clean generated files
make clean
```

### Make Variables
- `HOST`: STAC host (default: oneatlas)
- `DAYS`: Days to look back (default: 7)
- `BBOX`: Bounding box as "min_lon,min_lat,max_lon,max_lat"
- `TOP_N`: Number of top hotspots (default: 10)

## How It Works

1. **STAC Integration** - Uses the STAC (SpatioTemporal Asset Catalog) API standard to query multiple providers
2. **Smart Filtering** - Focuses on high-resolution taskable satellites (≤0.75m) to identify intentional surveillance
3. **Smart Pagination** - Automatically time-slices searches to bypass API limits (500 items/request)
4. **Location Intelligence** - Uses OpenStreetMap's Nominatim for reverse geocoding
5. **Pattern Detection** - Groups intersecting/overlapping images to identify surveillance hotspots

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

- **Language**: Shell scripts + SQL
- **Dependencies**: DuckDB, curl, jq
- **API**: UP42 STAC-compliant catalog API
- **Processing**: DuckDB spatial extension for geospatial analysis
- **Output**: GeoJSON FeatureCollection with hotspot clusters

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
