# To do

## Current Status
✅ **Minimal DuckDB Pipeline**: Core functionality working with shell scripts + DuckDB
✅ **STAC Data Fetching**: Automated time-slicing bypasses 500-item API limits
✅ **Spatial Clustering**: Intersection-based hotspot detection with GeoJSON output
✅ **Make-based Orchestration**: Clean, configurable pipeline with proper file targets

## Future Enhancements
- Add infrastructure analysis using Overpass API (similar to Python version)
- Implement reverse geocoding for human-readable location names
- Add visualization improvements to the map.html
- Support for additional STAC providers beyond UP42
- Performance optimizations for larger datasets

## Architecture Notes
- Current implementation is minimal and focused on core hotspot detection
- No Python dependencies - just DuckDB, curl, and shell scripts
- GeoJSON output compatible with mapping tools
- Makefile provides clean interface for customization
