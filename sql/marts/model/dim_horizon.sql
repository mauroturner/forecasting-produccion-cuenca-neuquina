-- Forecast horizons 1 to 12 months; the headline ones are the horizons the backtest validates.
DROP TABLE IF EXISTS dim_horizon;

CREATE TABLE dim_horizon AS
WITH RECURSIVE h (horizon) AS (
    SELECT 1
    UNION ALL
    SELECT horizon + 1 FROM h WHERE horizon < 12
)
SELECT
    horizon,
    CASE WHEN horizon = 1 THEN '1 mes' ELSE horizon || ' meses' END AS horizon_label,
    CASE WHEN horizon IN (1, 3, 6, 12) THEN 1 ELSE 0 END           AS is_headline
FROM h
ORDER BY horizon;
