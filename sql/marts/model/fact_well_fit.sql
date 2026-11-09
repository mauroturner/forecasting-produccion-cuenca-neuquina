-- Arps parameters of the latest 12 origins. A fit with rmse_log above 1.0 is kept and marked for review.
DROP TABLE IF EXISTS fact_well_fit;

CREATE TABLE fact_well_fit AS
SELECT
    f.well_id AS well_key,
    f.fluid   AS fluid_key,
    f.method  AS method_key,
    f.origin_period_key,
    f.run_key,
    f.peak_period_key,
    f.log_qi,
    f.qi_rate_per_day,
    f.di_nominal_per_month,
    f.b,
    f.d_lim_nominal_per_month,
    f.t_switch_months,
    f.d_effective_annual_initial,
    f.n_points,
    f.rmse_log,
    f.status,
    CASE WHEN f.rmse_log > 1.0 THEN 1 ELSE 0 END AS needs_review
FROM model_fit AS f
WHERE f.origin_period_key IN (SELECT origin_period_key FROM dim_origin)
ORDER BY f.well_id, f.fluid, f.method, f.origin_period_key;
