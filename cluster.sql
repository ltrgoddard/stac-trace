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

-- Extract coordinates and create spatial points
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
  ST_Point(lon, lat) as centroid,

  -- Grid clustering (1° resolution)
  floor(lat) as lat_grid,
  floor(lon) as lon_grid

FROM items;

-- Group by grid cell and filter significant hotspots
CREATE TABLE hotspots AS
SELECT
  lat_grid,
  lon_grid,
  count(*) as image_count,
  list(id) as item_ids,
  list(geometry) as geometries,
  list(properties) as properties_list
FROM items_with_coords
GROUP BY lat_grid, lon_grid
HAVING count(*) >= 5
ORDER BY count(*) DESC
LIMIT 10;

-- Generate nested GeoJSON FeatureCollection
SELECT json_object(
  'type', 'FeatureCollection',
  'features', (
    SELECT json_group_array(
      json_object(
        'type', 'FeatureCollection',
          'properties', json_object(
            'hotspot_id', concat(cast(lat_grid as varchar), ',', cast(lon_grid as varchar)),
            'image_count', image_count,
            'centroid_lat', lat_grid,
            'centroid_lon', lon_grid
          ),
        'features', (
          SELECT json_group_array(
            json_object(
              'type', 'Feature',
              'geometry', geometries[idx + 1],
              'properties', json_object(
                'id', item_ids[idx + 1],
                'datetime', (properties_list[idx + 1])->>'datetime',
                'collection', (properties_list[idx + 1])->>'constellation',
                'cloud_cover', ((properties_list[idx + 1])->'providerProperties')->>'cloudCover'
              )
            )
          )
          FROM (SELECT unnest(range(image_count)) as idx)
        )
      )
    ) FROM hotspots
  )
) as geojson;