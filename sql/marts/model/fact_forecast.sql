-- The forecast of the latest 12 origins (older ones stay in model_forecast, so no Parquet file grows without limit).
DROP TABLE IF EXISTS fact_forecast;

CREATE TABLE fact_forecast AS
SELECT
    f.well_id      AS well_key,
    f.fluid        AS fluid_key,
    f.method       AS method_key,
    f.origin_period_key,
    f.target_period_key,
    f.horizon,
    f.company_code AS company_key,
    f.p10,
    f.p50,
    f.p90,
    f.segment,
    f.is_selected,
    f.fit_status,
    f.run_key
FROM model_forecast AS f
WHERE f.origin_period_key IN (SELECT origin_period_key FROM dim_origin)
ORDER BY f.well_id, f.fluid, f.method, f.origin_period_key, f.horizon;
