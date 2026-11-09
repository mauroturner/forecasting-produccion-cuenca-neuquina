-- Violations: a (well, period) that appears more than once in stg_monthly_production.
SELECT well_id, period_key, COUNT(*) AS n_rows
FROM stg_monthly_production
GROUP BY well_id, period_key
HAVING COUNT(*) > 1;
