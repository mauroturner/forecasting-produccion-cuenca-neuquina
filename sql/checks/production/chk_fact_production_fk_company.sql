-- Violations: a production row with a company_key that is not in dim_company (a NULL key is allowed).
SELECT f.well_key, f.period_key, f.company_key
FROM fact_production_monthly AS f
LEFT JOIN dim_company AS d ON d.company_key = f.company_key
WHERE f.company_key IS NOT NULL AND d.company_key IS NULL;
