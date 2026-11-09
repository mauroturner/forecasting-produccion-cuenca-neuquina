-- One row per month from the first published period to the last one plus 12 months (the horizon of
-- the forecast), with no gaps.
DROP TABLE IF EXISTS dim_calendar;

CREATE TABLE dim_calendar AS
WITH RECURSIVE bounds AS (
    SELECT MIN(period_index) AS first_index, MAX(period_index) AS last_index
    FROM stg_monthly_production
),
months (period_index) AS (
    SELECT first_index FROM bounds WHERE first_index IS NOT NULL
    UNION ALL
    SELECT m.period_index + 1 FROM months AS m, bounds AS b WHERE m.period_index < b.last_index + 12
)
SELECT
    (m.period_index / 12) * 100 + (m.period_index % 12) + 1                      AS period_key,
    m.period_index                                                               AS period_index,
    date(printf('%04d-%02d-01', m.period_index / 12, m.period_index % 12 + 1))   AS month_start,
    m.period_index / 12                                                          AS year,
    m.period_index % 12 + 1                                                      AS month,
    CASE m.period_index % 12 + 1
        WHEN 1 THEN 'Enero' WHEN 2 THEN 'Febrero' WHEN 3 THEN 'Marzo' WHEN 4 THEN 'Abril'
        WHEN 5 THEN 'Mayo' WHEN 6 THEN 'Junio' WHEN 7 THEN 'Julio' WHEN 8 THEN 'Agosto'
        WHEN 9 THEN 'Septiembre' WHEN 10 THEN 'Octubre' WHEN 11 THEN 'Noviembre' ELSE 'Diciembre'
    END                                                                          AS month_name_es,
    (m.period_index % 12) / 3 + 1                                                AS quarter,
    printf('%04d-%02d', m.period_index / 12, m.period_index % 12 + 1)            AS year_month_label,
    CAST(strftime('%d', date(printf('%04d-%02d-01', m.period_index / 12, m.period_index % 12 + 1), '+1 month', '-1 day')) AS INTEGER)
                                                                                 AS days_in_month,
    CASE WHEN m.period_index <= b.last_index THEN 1 ELSE 0 END                   AS is_published,
    CASE WHEN m.period_index = b.last_index THEN 1 ELSE 0 END                    AS is_last_published
FROM months AS m, bounds AS b
ORDER BY m.period_index;

CREATE INDEX idx_dim_calendar_period_key ON dim_calendar (period_key);
