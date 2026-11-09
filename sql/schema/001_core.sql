-- Core tables of the warehouse (docs/plan.md, section 5). Safe to run repeatedly.

-- The validated subset exactly as published (typed, English names, no corrections).
CREATE TABLE IF NOT EXISTS raw_monthly_production (
    well_id             INTEGER NOT NULL,
    period_key          INTEGER NOT NULL,
    period_index        INTEGER NOT NULL,
    company_code        TEXT,
    company_name        TEXT,
    year                INTEGER NOT NULL,
    month               INTEGER NOT NULL,
    well_code           TEXT,
    oil_m3              REAL,
    gas_thousand_m3     REAL,
    water_m3            REAL,
    effective_days      REAL,
    extraction_method   TEXT,
    well_status         TEXT,
    well_type           TEXT,
    remarks             TEXT,
    loaded_at           TEXT,
    is_rectified        INTEGER,
    is_enabled          INTEGER,
    formation_code      TEXT,
    formation_name      TEXT,
    depth_m             REAL,
    concession_code     TEXT,
    concession_name     TEXT,
    field_code          TEXT,
    field_name          TEXT,
    basin               TEXT,
    province            TEXT,
    lon                 REAL,
    lat                 REAL,
    resource_type       TEXT,
    sub_resource_type   TEXT,
    project             TEXT,
    classification      TEXT,
    subclassification   TEXT,
    period_end          TEXT,
    PRIMARY KEY (well_id, period_key)
);

-- The same rows with the quality corrections applied and marked (sql/staging).
CREATE TABLE IF NOT EXISTS stg_monthly_production (
    well_id             INTEGER NOT NULL,
    period_key          INTEGER NOT NULL,
    period_index        INTEGER NOT NULL,
    year                INTEGER NOT NULL,
    month               INTEGER NOT NULL,
    days_in_month       INTEGER NOT NULL,
    company_code        TEXT,
    company_name        TEXT,
    well_code           TEXT,
    oil_m3              REAL,
    gas_thousand_m3     REAL,
    water_m3            REAL,
    effective_days      REAL,
    extraction_method   TEXT,
    well_status         TEXT,
    well_type           TEXT,
    remarks             TEXT,
    loaded_at           TEXT,
    is_rectified        INTEGER,
    formation_code      TEXT,
    formation_name      TEXT,
    depth_m             REAL,
    concession_code     TEXT,
    concession_name     TEXT,
    field_code          TEXT,
    field_name          TEXT,
    basin               TEXT,
    province            TEXT,
    lon                 REAL,
    lat                 REAL,
    resource_type       TEXT,
    sub_resource_type   TEXT,
    project             TEXT,
    classification      TEXT,
    subclassification   TEXT,
    is_producing        INTEGER NOT NULL,
    quality_flags       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (well_id, period_key)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_key                 TEXT PRIMARY KEY,
    started_at              TEXT,
    finished_at             TEXT,
    status                  TEXT,   -- unchanged, late, rejected, failed, ok
    source_url              TEXT,
    source_etag             TEXT,
    source_last_modified    TEXT,
    source_size             INTEGER,
    source_sha256           TEXT,
    last_period_key         INTEGER,
    rows_subset             INTEGER,
    wells_subset            INTEGER,
    revised_rows            INTEGER,
    message                 TEXT
);

CREATE TABLE IF NOT EXISTS validation_results (
    run_key         TEXT NOT NULL,
    rule_id         TEXT NOT NULL,
    name_es         TEXT NOT NULL,
    severity        TEXT NOT NULL,   -- bloqueante, advertencia, informativa
    passed          INTEGER NOT NULL,
    rows_affected   INTEGER NOT NULL,
    wells_affected  INTEGER NOT NULL,
    examples_json   TEXT NOT NULL,
    PRIMARY KEY (run_key, rule_id)
);

-- Totals of the validated subset per run and period: a history of what each publication said.
CREATE TABLE IF NOT EXISTS period_totals (
    run_key             TEXT NOT NULL,
    period_key          INTEGER NOT NULL,
    oil_m3              REAL NOT NULL,
    gas_thousand_m3     REAL NOT NULL,
    rows                INTEGER NOT NULL,
    PRIMARY KEY (run_key, period_key)
);

-- Rows of earlier periods that changed, appeared or disappeared when a run replaced the data.
CREATE TABLE IF NOT EXISTS load_revisions (
    run_key         TEXT NOT NULL,
    period_key      INTEGER NOT NULL,
    rows_changed    INTEGER NOT NULL,
    PRIMARY KEY (run_key, period_key)
);
