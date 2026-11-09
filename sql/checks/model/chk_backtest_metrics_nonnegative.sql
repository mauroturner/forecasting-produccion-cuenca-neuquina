-- Violations: a backtest component that cannot be negative is, or more pairs are covered than evaluated.
SELECT method_key, fluid_key, horizon, origin_period_key, age_bucket, sub_resource_type
FROM fact_backtest_metrics
WHERE n < 0 OR n_covered < 0 OR n_covered > n
   OR sum_actual < 0 OR sum_p10 < 0 OR sum_p50 < 0 OR sum_p90 < 0
   OR sum_abs_error < 0 OR sum_sq_error < 0 OR sum_pinball < 0;
