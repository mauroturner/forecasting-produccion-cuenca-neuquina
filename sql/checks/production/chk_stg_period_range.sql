-- Violations: a month outside 1-12, or a period_key / period_index that does not match year and month.
SELECT well_id, period_key, year, month
FROM stg_monthly_production
WHERE month NOT BETWEEN 1 AND 12
   OR period_key <> year * 100 + month
   OR period_index <> year * 12 + month - 1;
