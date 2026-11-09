-- The summary of the backtest per method, fluid, horizon and segment, with its verdict.
DROP TABLE IF EXISTS fact_model_summary;

CREATE TABLE fact_model_summary AS
SELECT
    s.method AS method_key,
    s.fluid  AS fluid_key,
    s.horizon,
    s.segment,
    s.run_key,
    s.n_series,
    s.n_points,
    s.mae,
    s.rmse,
    s.wape,
    s.bias,
    s.coverage,
    s.scaled_pinball,
    s.share_beats_naive_last,
    s.share_beats_naive_mean3,
    s.fallback_rate,
    s.basin_band_coverage,
    s.coverage_verdict,
    s.verdict_es
FROM model_summary AS s
ORDER BY s.method, s.fluid, s.horizon, s.segment;
