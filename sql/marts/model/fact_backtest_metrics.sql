-- Additive components of the backtest per method, fluid, horizon, origin, age bucket and sub-resource type.
DROP TABLE IF EXISTS fact_backtest_metrics;

CREATE TABLE fact_backtest_metrics AS
SELECT
    m.method AS method_key,
    m.fluid  AS fluid_key,
    m.horizon,
    m.origin_period_key,
    m.age_bucket,
    m.sub_resource_type,
    m.run_key,
    m.n,
    m.sum_actual,
    m.sum_p10,
    m.sum_p50,
    m.sum_p90,
    m.sum_abs_error,
    m.sum_sq_error,
    m.sum_error,
    m.n_covered,
    m.sum_pinball
FROM model_backtest_metrics AS m
ORDER BY m.method, m.fluid, m.horizon, m.origin_period_key, m.age_bucket, m.sub_resource_type;
