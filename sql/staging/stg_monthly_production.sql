-- Rebuilds stg_monthly_production from raw_monthly_production: the quality corrections of
-- docs/plan.md section 6 (rules V12-V15), each one marked in quality_flags (D18).
--   NEG_VOLUME          a negative volume of oil, gas or water; that volume becomes NULL
--   TEF_GT_DAYS         effective days above the days of the month; effective_days becomes NULL
--   TEF_ZERO_WITH_PROD  effective days = 0 with oil or gas > 0; kept
--   VOLUME_CEILING      oil or gas above the plausible monthly ceiling; kept
-- Parameters: :oil_ceiling_m3, :gas_ceiling_thousand_m3.

DELETE FROM stg_monthly_production;

INSERT INTO stg_monthly_production (
    well_id, period_key, period_index, year, month, days_in_month,
    company_code, company_name, well_code,
    oil_m3, gas_thousand_m3, water_m3, effective_days,
    extraction_method, well_status, well_type, remarks, loaded_at, is_rectified,
    formation_code, formation_name, depth_m, concession_code, concession_name,
    field_code, field_name, basin, province, lon, lat,
    resource_type, sub_resource_type, project, classification, subclassification,
    is_producing, quality_flags
)
WITH base AS (
    SELECT
        r.*,
        CAST(strftime('%d', date(printf('%04d-%02d-01', r.year, r.month), '+1 month', '-1 day')) AS INTEGER) AS days_in_month
    FROM raw_monthly_production AS r
),
corrected AS (
    SELECT
        b.*,
        CASE WHEN b.oil_m3 < 0 THEN NULL ELSE b.oil_m3 END AS oil_fixed,
        CASE WHEN b.gas_thousand_m3 < 0 THEN NULL ELSE b.gas_thousand_m3 END AS gas_fixed,
        CASE WHEN b.water_m3 < 0 THEN NULL ELSE b.water_m3 END AS water_fixed,
        CASE WHEN b.effective_days > b.days_in_month THEN NULL ELSE b.effective_days END AS tef_fixed,
        trim(
            CASE WHEN b.oil_m3 < 0 OR b.gas_thousand_m3 < 0 OR b.water_m3 < 0 THEN 'NEG_VOLUME;' ELSE '' END
            || CASE WHEN b.effective_days > b.days_in_month THEN 'TEF_GT_DAYS;' ELSE '' END
            || CASE WHEN b.effective_days = 0 AND (b.oil_m3 > 0 OR b.gas_thousand_m3 > 0) THEN 'TEF_ZERO_WITH_PROD;' ELSE '' END
            || CASE WHEN b.oil_m3 > :oil_ceiling_m3 OR b.gas_thousand_m3 > :gas_ceiling_thousand_m3 THEN 'VOLUME_CEILING;' ELSE '' END,
            ';'
        ) AS flags
    FROM base AS b
)
SELECT
    c.well_id, c.period_key, c.period_index, c.year, c.month, c.days_in_month,
    c.company_code, c.company_name, c.well_code,
    c.oil_fixed, c.gas_fixed, c.water_fixed, c.tef_fixed,
    c.extraction_method, c.well_status, c.well_type, c.remarks, c.loaded_at, c.is_rectified,
    c.formation_code, c.formation_name, c.depth_m, c.concession_code, c.concession_name,
    c.field_code, c.field_name, c.basin, c.province, c.lon, c.lat,
    c.resource_type, c.sub_resource_type, c.project, c.classification, c.subclassification,
    CASE WHEN COALESCE(c.oil_fixed, 0) > 0 OR COALESCE(c.gas_fixed, 0) > 0 THEN 1 ELSE 0 END,
    c.flags
FROM corrected AS c;
