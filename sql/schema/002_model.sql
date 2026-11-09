-- Tables written by the model tasks: fits, forecasts, backtest metrics and the summary
-- (docs/plan.md, section 5). Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS model_fit (
    origin_period_key           INTEGER NOT NULL,
    well_id                     INTEGER NOT NULL,
    fluid                       TEXT NOT NULL,
    method                      TEXT NOT NULL,
    run_key                     TEXT NOT NULL,
    peak_period_key             INTEGER,
    log_qi                      REAL,
    qi_rate_per_day             REAL,
    di_nominal_per_month        REAL,
    b                           REAL,
    d_lim_nominal_per_month     REAL,
    t_switch_months             REAL,
    d_effective_annual_initial  REAL,
    n_points                    INTEGER,
    rmse_log                    REAL,
    status                      TEXT,
    PRIMARY KEY (origin_period_key, well_id, fluid, method)
);

CREATE TABLE IF NOT EXISTS model_forecast (
    origin_period_key   INTEGER NOT NULL,
    well_id             INTEGER NOT NULL,
    fluid               TEXT NOT NULL,
    method              TEXT NOT NULL,
    horizon             INTEGER NOT NULL,
    run_key             TEXT NOT NULL,
    target_period_key   INTEGER NOT NULL,
    company_code        TEXT,
    p10                 REAL NOT NULL,
    p50                 REAL NOT NULL,
    p90                 REAL NOT NULL,
    segment             TEXT,
    is_selected         INTEGER NOT NULL DEFAULT 0,
    fit_status          TEXT,
    PRIMARY KEY (origin_period_key, well_id, fluid, method, horizon)
);

CREATE TABLE IF NOT EXISTS model_fitted_curve (
    origin_period_key   INTEGER NOT NULL,
    well_id             INTEGER NOT NULL,
    fluid               TEXT NOT NULL,
    period_key          INTEGER NOT NULL,
    fitted_volume       REAL NOT NULL,
    PRIMARY KEY (origin_period_key, well_id, fluid, period_key)
);

CREATE TABLE IF NOT EXISTS model_backtest_metrics (
    method              TEXT NOT NULL,
    fluid               TEXT NOT NULL,
    horizon             INTEGER NOT NULL,
    origin_period_key   INTEGER NOT NULL,
    age_bucket          TEXT NOT NULL,
    sub_resource_type   TEXT NOT NULL,
    run_key             TEXT NOT NULL,
    n                   INTEGER NOT NULL,
    sum_actual          REAL NOT NULL,
    sum_p10             REAL NOT NULL,
    sum_p50             REAL NOT NULL,
    sum_p90             REAL NOT NULL,
    sum_abs_error       REAL NOT NULL,
    sum_sq_error        REAL NOT NULL,
    sum_error           REAL NOT NULL,
    n_covered           INTEGER NOT NULL,
    sum_pinball         REAL NOT NULL,
    PRIMARY KEY (method, fluid, horizon, origin_period_key, age_bucket, sub_resource_type)
);

CREATE TABLE IF NOT EXISTS model_summary (
    method                  TEXT NOT NULL,
    fluid                   TEXT NOT NULL,
    horizon                 INTEGER NOT NULL,
    segment                 TEXT NOT NULL,
    run_key                 TEXT NOT NULL,
    n_series                INTEGER,
    n_points                INTEGER,
    mae                     REAL,
    rmse                    REAL,
    wape                    REAL,
    bias                    REAL,
    coverage                REAL,
    scaled_pinball          REAL,
    share_beats_naive_last  REAL,
    share_beats_naive_mean3 REAL,
    fallback_rate           REAL,
    basin_band_coverage     REAL,
    coverage_verdict        TEXT,
    verdict_es              TEXT,
    PRIMARY KEY (method, fluid, horizon, segment)
);

CREATE TABLE IF NOT EXISTS model_selection (
    fluid           TEXT NOT NULL,
    segment         TEXT NOT NULL,
    run_key         TEXT NOT NULL,
    method          TEXT NOT NULL,
    criterion_value REAL,
    rule            TEXT,
    PRIMARY KEY (fluid, segment)
);
