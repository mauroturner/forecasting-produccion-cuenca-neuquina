-- Counts, per earlier period, the rows that a new publication changed, dropped or added (RF06).
-- Runs while the previous publication is still in raw_monthly_production and the new one is in
-- tmp_raw_new. A volume changed when it differs by more than 1e-6 or became/stopped being NULL.
-- Parameters: :run_key, :previous_last_period_key (NULL on the first load).
DELETE FROM load_revisions WHERE run_key = :run_key;

INSERT INTO load_revisions (run_key, period_key, rows_changed)
SELECT :run_key, period_key, COUNT(*)
FROM (
    -- changed or disappeared
    SELECT o.period_key
    FROM raw_monthly_production AS o
    LEFT JOIN tmp_raw_new AS n ON n.well_id = o.well_id AND n.period_key = o.period_key
    WHERE o.period_key <= :previous_last_period_key
      AND (
          n.well_id IS NULL
          OR (o.oil_m3 IS NOT n.oil_m3 AND (o.oil_m3 IS NULL OR n.oil_m3 IS NULL OR ABS(o.oil_m3 - n.oil_m3) > 1e-6))
          OR (o.gas_thousand_m3 IS NOT n.gas_thousand_m3
              AND (o.gas_thousand_m3 IS NULL OR n.gas_thousand_m3 IS NULL OR ABS(o.gas_thousand_m3 - n.gas_thousand_m3) > 1e-6))
          OR (o.water_m3 IS NOT n.water_m3 AND (o.water_m3 IS NULL OR n.water_m3 IS NULL OR ABS(o.water_m3 - n.water_m3) > 1e-6))
      )
    UNION ALL
    -- added to a period that was already published
    SELECT n.period_key
    FROM tmp_raw_new AS n
    LEFT JOIN raw_monthly_production AS o ON o.well_id = n.well_id AND o.period_key = n.period_key
    WHERE n.period_key <= :previous_last_period_key AND o.well_id IS NULL
)
GROUP BY period_key;
