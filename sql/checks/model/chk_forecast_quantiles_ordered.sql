-- Violations: a forecast whose quantiles are not ordered (P10 <= P50 <= P90) or are negative.
SELECT well_key, fluid_key, method_key, origin_period_key, horizon, p10, p50, p90
FROM fact_forecast
WHERE NOT (p10 <= p50 AND p50 <= p90) OR p10 < 0;
