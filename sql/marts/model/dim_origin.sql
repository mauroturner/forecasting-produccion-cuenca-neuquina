-- The latest origins of the forecast (from model_forecast and model_fit), at most :max_origins, and the run that made each.
DROP TABLE IF EXISTS dim_origin;

CREATE TABLE dim_origin AS
WITH seen AS (
    SELECT origin_period_key, run_key FROM model_forecast
    UNION
    SELECT origin_period_key, run_key FROM model_fit
),
origins AS (
    SELECT origin_period_key, MAX(run_key) AS run_key
    FROM seen
    GROUP BY origin_period_key
    ORDER BY origin_period_key DESC
    LIMIT :max_origins
)
SELECT
    origin_period_key,
    printf('%04d-%02d', origin_period_key / 100, origin_period_key % 100)       AS origin_label,
    CASE WHEN origin_period_key = (SELECT MAX(origin_period_key) FROM origins) THEN 1 ELSE 0 END AS is_latest,
    run_key
FROM origins
ORDER BY origin_period_key;
