-- Violations: a production row whose well is not in dim_well.
SELECT f.well_key, f.period_key
FROM fact_production_monthly AS f
LEFT JOIN dim_well AS d ON d.well_key = f.well_key
WHERE d.well_key IS NULL;
