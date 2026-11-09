-- One row per run of the pipeline.
DROP TABLE IF EXISTS dim_pipeline_run;

CREATE TABLE dim_pipeline_run AS
SELECT
    run_key, started_at, finished_at, status, source_url, source_etag, source_last_modified, source_size,
    source_sha256, last_period_key, rows_subset, wells_subset, revised_rows, message
FROM pipeline_runs
ORDER BY run_key;
