-- One row per well and month with the corrected volumes. Parameter: :run_key.
DROP TABLE IF EXISTS fact_production_monthly;

CREATE TABLE fact_production_monthly AS
SELECT
    well_id            AS well_key,
    period_key,
    company_code       AS company_key,
    oil_m3,
    gas_thousand_m3,
    water_m3,
    effective_days,
    is_producing,
    well_type,
    well_status,
    extraction_method,
    quality_flags,
    :run_key           AS run_key
FROM stg_monthly_production
ORDER BY well_id, period_key;

CREATE INDEX idx_fact_production_well ON fact_production_monthly (well_key);
CREATE INDEX idx_fact_production_period ON fact_production_monthly (period_key);
