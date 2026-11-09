-- One row per operator code, with its most recent name.
DROP TABLE IF EXISTS dim_company;

CREATE TABLE dim_company AS
SELECT company_code AS company_key, company_name
FROM (
    SELECT
        company_code,
        company_name,
        ROW_NUMBER() OVER (PARTITION BY company_code ORDER BY period_key DESC, well_id) AS rn
    FROM stg_monthly_production
    WHERE company_code IS NOT NULL
)
WHERE rn = 1
ORDER BY company_key;

CREATE INDEX idx_dim_company_key ON dim_company (company_key);
