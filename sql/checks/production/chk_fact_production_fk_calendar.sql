-- Violations: a production row whose month is not in dim_calendar.
SELECT f.well_key, f.period_key
FROM fact_production_monthly AS f
LEFT JOIN dim_calendar AS d ON d.period_key = f.period_key
WHERE d.period_key IS NULL;
