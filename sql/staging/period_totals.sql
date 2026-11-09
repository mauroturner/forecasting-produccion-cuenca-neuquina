-- Totals of the subset that was just loaded, per period, for this run. Parameter: :run_key.
DELETE FROM period_totals WHERE run_key = :run_key;

INSERT INTO period_totals (run_key, period_key, oil_m3, gas_thousand_m3, rows)
SELECT :run_key, period_key, COALESCE(SUM(oil_m3), 0), COALESCE(SUM(gas_thousand_m3), 0), COUNT(*)
FROM raw_monthly_production
GROUP BY period_key;
