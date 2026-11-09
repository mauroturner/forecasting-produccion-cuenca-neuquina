-- Violations: a row of the other model facts that points to a missing dimension row.
SELECT 'fact_well_fit.well' AS reference, f.well_key AS missing_key
FROM fact_well_fit AS f LEFT JOIN dim_well AS d ON d.well_key = f.well_key WHERE d.well_key IS NULL
UNION ALL
SELECT 'fact_well_fit.fluid', f.fluid_key
FROM fact_well_fit AS f LEFT JOIN dim_fluid AS d ON d.fluid_key = f.fluid_key WHERE d.fluid_key IS NULL
UNION ALL
SELECT 'fact_well_fit.method', f.method_key
FROM fact_well_fit AS f LEFT JOIN dim_method AS d ON d.method_key = f.method_key WHERE d.method_key IS NULL
UNION ALL
SELECT 'fact_well_fit.origin', f.origin_period_key
FROM fact_well_fit AS f LEFT JOIN dim_origin AS d ON d.origin_period_key = f.origin_period_key WHERE d.origin_period_key IS NULL
UNION ALL
SELECT 'fact_fitted_curve.well', f.well_key
FROM fact_fitted_curve AS f LEFT JOIN dim_well AS d ON d.well_key = f.well_key WHERE d.well_key IS NULL
UNION ALL
SELECT 'fact_fitted_curve.fluid', f.fluid_key
FROM fact_fitted_curve AS f LEFT JOIN dim_fluid AS d ON d.fluid_key = f.fluid_key WHERE d.fluid_key IS NULL
UNION ALL
SELECT 'fact_fitted_curve.period', f.period_key
FROM fact_fitted_curve AS f LEFT JOIN dim_calendar AS d ON d.period_key = f.period_key WHERE d.period_key IS NULL
UNION ALL
SELECT 'fact_backtest_metrics.method', f.method_key
FROM fact_backtest_metrics AS f LEFT JOIN dim_method AS d ON d.method_key = f.method_key WHERE d.method_key IS NULL
UNION ALL
SELECT 'fact_backtest_metrics.fluid', f.fluid_key
FROM fact_backtest_metrics AS f LEFT JOIN dim_fluid AS d ON d.fluid_key = f.fluid_key WHERE d.fluid_key IS NULL
UNION ALL
SELECT 'fact_backtest_metrics.horizon', f.horizon
FROM fact_backtest_metrics AS f LEFT JOIN dim_horizon AS d ON d.horizon = f.horizon WHERE d.horizon IS NULL
UNION ALL
SELECT 'fact_backtest_metrics.origin', f.origin_period_key
FROM fact_backtest_metrics AS f LEFT JOIN dim_calendar AS d ON d.period_key = f.origin_period_key WHERE d.period_key IS NULL
UNION ALL
SELECT 'fact_model_summary.method', f.method_key
FROM fact_model_summary AS f LEFT JOIN dim_method AS d ON d.method_key = f.method_key WHERE d.method_key IS NULL
UNION ALL
SELECT 'fact_model_summary.fluid', f.fluid_key
FROM fact_model_summary AS f LEFT JOIN dim_fluid AS d ON d.fluid_key = f.fluid_key WHERE d.fluid_key IS NULL
UNION ALL
SELECT 'fact_model_summary.horizon', f.horizon
FROM fact_model_summary AS f LEFT JOIN dim_horizon AS d ON d.horizon = f.horizon WHERE d.horizon IS NULL
UNION ALL
SELECT 'fact_validation.run', f.run_key
FROM fact_validation AS f LEFT JOIN dim_pipeline_run AS d ON d.run_key = f.run_key WHERE d.run_key IS NULL;
