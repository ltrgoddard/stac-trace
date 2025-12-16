-- DuckDB SQL for STAC hotspots analysis from persistent database
-- Usage: duckdb data/stac.duckdb -json < analyze.sql
-- Reads from items table, outputs GeoJSON to stdout

-- Load spatial extension
LOAD spatial;

-- Extract coordinates and create spatial geometries
-- Grid size of 0.1 degrees (~11km at equator) for clustering
CREATE TEMP TABLE items_with_coords AS
SELECT
  id,
  geometry,
  properties,

  -- Extract centroid coordinates with fallbacks
  COALESCE(
    (properties->'providerProperties'->'geometryCentroid'->>'lat')::FLOAT,
    ((bbox->>1)::FLOAT + (bbox->>3)::FLOAT)/2
  ) as lat,

  COALESCE(
    (properties->'providerProperties'->'geometryCentroid'->>'lon')::FLOAT,
    ((bbox->>0)::FLOAT + (bbox->>2)::FLOAT)/2
  ) as lon

FROM items
WHERE DATE_FILTER_PLACEHOLDER;

-- Add geometry and grid cell
CREATE TEMP TABLE items_with_geoms AS
SELECT
  id,
  ST_GeomFromGeoJSON(geometry::VARCHAR) as geom,
  properties,
  lat,
  lon,
  -- Grid cell for clustering (0.1 degree resolution)
  FLOOR(lat / 0.1)::INTEGER as grid_lat,
  FLOOR(lon / 0.1)::INTEGER as grid_lon
FROM items_with_coords
WHERE (properties->>'constellation')::VARCHAR NOT IN ('spot')
  AND (properties->>'resolution')::FLOAT <= 0.75;

-- Grid-based clustering: group images by grid cell
-- Also merge with adjacent cells to avoid boundary splitting
CREATE TEMP TABLE grid_clusters AS
SELECT
  -- Normalize grid to handle adjacent cell merging
  FLOOR(grid_lat / 2) * 2 as cluster_lat,
  FLOOR(grid_lon / 2) * 2 as cluster_lon,
  COUNT(*) as image_count,
  list(id) as item_ids,
  array_agg(geom) as geometry_array,
  list(properties) as properties_list,
  AVG(lon) as centroid_lon,
  AVG(lat) as centroid_lat
FROM items_with_geoms
GROUP BY cluster_lat, cluster_lon
HAVING COUNT(*) >= 5;

-- Extract datetime and constellation from each cluster's properties
CREATE TEMP TABLE cluster_props AS
SELECT
  h.cluster_lat,
  h.cluster_lon,
  json_extract_string(prop, '$.datetime') as datetime_str,
  json_extract_string(prop, '$.constellation') as constellation
FROM grid_clusters h, unnest(h.properties_list) as t(prop);

-- Aggregate properties per cluster
CREATE TEMP TABLE cluster_agg AS
SELECT
  cluster_lat,
  cluster_lon,
  max(datetime_str::TIMESTAMP) as latest_datetime,
  min(datetime_str::TIMESTAMP) as earliest_datetime,
  mode(constellation) as primary_collection
FROM cluster_props
GROUP BY cluster_lat, cluster_lon;

-- Create merged cluster features
CREATE TEMP TABLE cluster_features AS
SELECT
  ST_AsGeoJSON(
    ST_Buffer(
      ST_ConvexHull(
        ST_Collect(h.geometry_array)
      ),
      0
    )
  ) as geometry,
  h.cluster_lat || '_' || h.cluster_lon as hotspot_id,
  h.image_count as hotspot_image_count,
  h.item_ids as image_ids,
  h.centroid_lat as hotspot_centroid_lat,
  h.centroid_lon as hotspot_centroid_lon,
  ca.latest_datetime,
  ca.earliest_datetime,
  ca.primary_collection
FROM grid_clusters h
LEFT JOIN cluster_agg ca ON h.cluster_lat = ca.cluster_lat AND h.cluster_lon = ca.cluster_lon;

-- Generate merged cluster GeoJSON FeatureCollection
SELECT to_json({
  type: 'FeatureCollection',
  features: (
    SELECT list({
      type: 'Feature',
      geometry: json(geometry),
      properties: {
        hotspot_id: hotspot_id,
        hotspot_image_count: hotspot_image_count,
        image_ids: image_ids,
        hotspot_centroid_lat: hotspot_centroid_lat,
        hotspot_centroid_lon: hotspot_centroid_lon,
        latest_datetime: latest_datetime::VARCHAR,
        earliest_datetime: earliest_datetime::VARCHAR,
        primary_collection: primary_collection
      }
    }) FROM cluster_features
  )
}) as geojson;
