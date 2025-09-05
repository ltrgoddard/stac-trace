-- DuckDB SQL for STAC hotspots analysis and GeoJSON generation
-- Usage: duckdb -json < cluster.sql

-- Load spatial extension
INSTALL spatial;
LOAD spatial;

-- Read STAC data from file and extract features
CREATE TABLE raw_data AS
SELECT * FROM read_json('DATA_FILE_PLACEHOLDER');

CREATE TABLE items AS
SELECT
  unnest(features) as item
FROM raw_data;

-- Extract coordinates and create spatial geometries
CREATE TABLE items_with_coords AS
SELECT
  item->'properties'->>'id' as id,
  item->'geometry' as geometry,
  item->'properties' as properties,

  -- Extract centroid coordinates with fallbacks
  COALESCE(
    (item->'properties'->'providerProperties'->'geometryCentroid'->>'lat')::FLOAT,
    ((item->'bbox'->>1)::FLOAT + (item->'bbox'->>3)::FLOAT)/2
  ) as lat,

  COALESCE(
    (item->'properties'->'providerProperties'->'geometryCentroid'->>'lon')::FLOAT,
    ((item->'bbox'->>0)::FLOAT + (item->'bbox'->>2)::FLOAT)/2
  ) as lon,

  -- Create spatial point
  ST_Point(lon, lat) as centroid

FROM items;

-- Convert JSON geometries to proper GEOMETRY type
CREATE TABLE items_with_geoms AS
SELECT
  id,
  ST_GeomFromGeoJSON(geometry::VARCHAR) as geom,
  properties,
  lat,
  lon,
  centroid
FROM items_with_coords;

-- Find all pairs of intersecting images
CREATE TABLE intersections AS
SELECT
  a.id as id1,
  b.id as id2,
  a.geom as geom1,
  b.geom as geom2,
  a.properties as props1,
  b.properties as props2
FROM items_with_geoms a
JOIN items_with_geoms b ON a.id < b.id
WHERE ST_Intersects(a.geom, b.geom);

-- Use a simpler approach: group by spatial proximity
-- For each image, find all images that intersect with it or its neighbors
CREATE TABLE spatial_groups AS
WITH intersection_groups AS (
  SELECT
    id1 as image_id,
    id1 as group_id
  FROM intersections

  UNION

  SELECT
    id2 as image_id,
    id1 as group_id
  FROM intersections
),

-- Assign each image to its smallest group ID
grouped_images AS (
  SELECT
    image_id,
    MIN(group_id) as component_id
  FROM intersection_groups
  GROUP BY image_id
)

SELECT
  g.image_id,
  COALESCE(g.component_id, i.id) as component_id,
  i.geom,
  i.properties
FROM items_with_geoms i
LEFT JOIN grouped_images g ON i.id = g.image_id;

-- Group by spatial group and filter significant hotspots
CREATE TABLE hotspots AS
SELECT
  component_id,
  count(*) as image_count,
  list(image_id) as item_ids,
  array_agg(geom) as geometry_array,
  list(properties) as properties_list,

  -- Use average of centroid coordinates as approximation
  avg(ST_X(ST_Centroid(geom))) as centroid_lon,
  avg(ST_Y(ST_Centroid(geom))) as centroid_lat

FROM spatial_groups
GROUP BY component_id
HAVING count(*) >= 5
ORDER BY count(*) DESC;

-- Create merged cluster features
CREATE TABLE cluster_features AS
SELECT
  ST_AsGeoJSON(
    ST_Buffer(
      ST_ConvexHull(
        ST_Collect(geometry_array)
      ),
      0
    )
  ) as geometry,
  component_id as hotspot_id,
  image_count as hotspot_image_count,
  item_ids as image_ids,
  centroid_lat as hotspot_centroid_lat,
  centroid_lon as hotspot_centroid_lon,
  -- Get most recent datetime from the cluster
  (SELECT max((prop->>'datetime')::TIMESTAMP)
   FROM unnest(properties_list) as prop) as latest_datetime,
  -- Get most common collection
  (SELECT mode((prop->>'constellation')::VARCHAR)
   FROM unnest(properties_list) as prop) as primary_collection
FROM hotspots;

-- Generate merged cluster GeoJSON FeatureCollection
SELECT json_object(
  'type', 'FeatureCollection',
  'features', (
    SELECT json_group_array(
      json_object(
        'type', 'Feature',
        'geometry', geometry,
        'properties', json_object(
          'hotspot_id', hotspot_id,
          'hotspot_image_count', hotspot_image_count,
          'image_ids', image_ids,
          'hotspot_centroid_lat', hotspot_centroid_lat,
          'hotspot_centroid_lon', hotspot_centroid_lon,
          'latest_datetime', latest_datetime,
          'primary_collection', primary_collection
        )
      )
    ) FROM cluster_features
  )
) as geojson;