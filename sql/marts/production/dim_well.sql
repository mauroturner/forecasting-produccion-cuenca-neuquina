-- One row per well. Attributes that belong to the well come from its latest row (V18); the ones that
-- change over time (operator, well type, status, extraction method) appear as *_current / *_latest.
-- Corrections, marked in quality_flags (D18):
--   COORDS_SWAPPED      lon and lat were exchanged (V16): they are exchanged back
--   COORDS_OUTSIDE      coordinates outside the basin or missing (V16): both become NULL
--   DEPTH_INVALID       depth outside the valid range (V17): becomes NULL
--   FIXED_ATTR_CHANGED  a fixed attribute has more than one value in the well (V18): latest is kept
-- Parameters: :lon_min, :lon_max, :lat_min, :lat_max, :depth_min_m, :depth_max_m.
DROP TABLE IF EXISTS dim_well;

CREATE TABLE dim_well AS
WITH latest AS (
    SELECT s.*, ROW_NUMBER() OVER (PARTITION BY s.well_id ORDER BY s.period_key DESC) AS rn
    FROM stg_monthly_production AS s
),
aggregated AS (
    SELECT
        well_id,
        MIN(CASE WHEN is_producing = 1 THEN period_key END) AS first_production_period_key,
        MAX(period_key)                                     AS last_report_period_key,
        SUM(is_producing)                                   AS months_with_production,
        COALESCE(SUM(oil_m3), 0)                            AS cum_oil_m3,
        COALESCE(SUM(gas_thousand_m3), 0)                   AS cum_gas_thousand_m3,
        COALESCE(SUM(water_m3), 0)                          AS cum_water_m3,
        CASE WHEN COUNT(DISTINCT well_code) > 1 OR COUNT(DISTINCT province) > 1
                  OR COUNT(DISTINCT concession_code) > 1 OR COUNT(DISTINCT concession_name) > 1
                  OR COUNT(DISTINCT field_code) > 1 OR COUNT(DISTINCT field_name) > 1
                  OR COUNT(DISTINCT formation_code) > 1 OR COUNT(DISTINCT formation_name) > 1
                  OR COUNT(DISTINCT sub_resource_type) > 1 OR COUNT(DISTINCT lon) > 1
                  OR COUNT(DISTINCT lat) > 1 OR COUNT(DISTINCT depth_m) > 1
             THEN 1 ELSE 0 END                              AS attributes_changed
    FROM stg_monthly_production
    GROUP BY well_id
),
located AS (
    SELECT
        l.*,
        COALESCE(l.lon BETWEEN :lon_min AND :lon_max AND l.lat BETWEEN :lat_min AND :lat_max, 0) AS coords_ok,
        COALESCE(l.lat BETWEEN :lon_min AND :lon_max AND l.lon BETWEEN :lat_min AND :lat_max, 0) AS coords_swapped
    FROM latest AS l
    WHERE l.rn = 1
)
SELECT
    t.well_id                                                   AS well_key,
    t.well_code,
    t.province,
    t.concession_code,
    t.concession_name,
    t.field_code,
    t.field_name,
    t.formation_code,
    t.formation_name,
    t.sub_resource_type,
    t.basin,
    CASE WHEN t.coords_ok = 1 THEN t.lon WHEN t.coords_swapped = 1 THEN t.lat END  AS lon,
    CASE WHEN t.coords_ok = 1 THEN t.lat WHEN t.coords_swapped = 1 THEN t.lon END  AS lat,
    CASE WHEN t.depth_m BETWEEN :depth_min_m AND :depth_max_m THEN t.depth_m END   AS depth_m,
    t.company_code                                              AS operator_current_key,
    t.company_name                                              AS operator_current_name,
    t.well_type                                                 AS well_type_latest,
    t.well_status                                               AS well_status_latest,
    t.extraction_method                                         AS extraction_method_latest,
    a.first_production_period_key,
    a.last_report_period_key,
    a.months_with_production,
    a.cum_oil_m3,
    a.cum_gas_thousand_m3,
    a.cum_water_m3,
    trim(
        CASE WHEN t.coords_ok = 0 AND t.coords_swapped = 1 THEN 'COORDS_SWAPPED;' ELSE '' END
        || CASE WHEN t.coords_ok = 0 AND t.coords_swapped = 0 THEN 'COORDS_OUTSIDE;' ELSE '' END
        || CASE WHEN t.depth_m IS NOT NULL AND NOT (t.depth_m BETWEEN :depth_min_m AND :depth_max_m) THEN 'DEPTH_INVALID;' ELSE '' END
        || CASE WHEN a.attributes_changed = 1 THEN 'FIXED_ATTR_CHANGED;' ELSE '' END,
        ';'
    )                                                           AS quality_flags
FROM located AS t
JOIN aggregated AS a ON a.well_id = t.well_id
ORDER BY t.well_id;

CREATE INDEX idx_dim_well_key ON dim_well (well_key);
