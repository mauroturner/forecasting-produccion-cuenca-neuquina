-- Violations: a negative volume left in the corrected table (the staging turns them into NULL).
SELECT well_id, period_key, oil_m3, gas_thousand_m3, water_m3
FROM stg_monthly_production
WHERE oil_m3 < 0 OR gas_thousand_m3 < 0 OR water_m3 < 0;
