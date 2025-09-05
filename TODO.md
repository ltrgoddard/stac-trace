# To do

✅ ~~Use OpenStreetMap's Overpass API to grab details of significant infrastructure and buildings within each hotspot (using the actual image boundaries), surfacing these along with the hotspot results.~~ DONE

## Completed enhancements
- Added intelligent significance scoring to prioritize major infrastructure
- Expanded query to include commercial activity, data centers, universities, hospitals, etc.
- Implemented smart filtering to show only the most significant 3-5 items per category
- Made infrastructure queries optional with `--no-infrastructure` flag (due to Overpass API timeouts)
- Organized results into strategic categories: Strategic, Airports, Power, Transport, Technology, etc.

## Alternative APIs for future consideration
- Google Places API - Detailed business data (requires API key)
- Foursquare Places API - Venue/business data (free tier available)
- MapBox Geocoding API - Points of interest (requires token)
