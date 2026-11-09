-- Violations: a forecast row that points to a missing dimension row. company_key may be empty.
SELECT 'well' AS dimension, f.well_key AS missing_key
FROM fact_forecast AS f LEFT JOIN dim_well AS d ON d.well_key = f.well_key WHERE d.well_key IS NULL
UNION ALL
SELECT 'company', f.company_key
FROM fact_forecast AS f LEFT JOIN dim_company AS d ON d.company_key = f.company_key
WHERE f.company_key IS NOT NULL AND d.company_key IS NULL
UNION ALL
SELECT 'fluid', f.fluid_key
FROM fact_forecast AS f LEFT JOIN dim_fluid AS d ON d.fluid_key = f.fluid_key WHERE d.fluid_key IS NULL
UNION ALL
SELECT 'method', f.method_key
FROM fact_forecast AS f LEFT JOIN dim_method AS d ON d.method_key = f.method_key WHERE d.method_key IS NULL
UNION ALL
SELECT 'origin', f.origin_period_key
FROM fact_forecast AS f LEFT JOIN dim_origin AS d ON d.origin_period_key = f.origin_period_key WHERE d.origin_period_key IS NULL
UNION ALL
SELECT 'horizon', f.horizon
FROM fact_forecast AS f LEFT JOIN dim_horizon AS d ON d.horizon = f.horizon WHERE d.horizon IS NULL
UNION ALL
SELECT 'calendar', f.target_period_key
FROM fact_forecast AS f LEFT JOIN dim_calendar AS d ON d.period_key = f.target_period_key WHERE d.period_key IS NULL;
