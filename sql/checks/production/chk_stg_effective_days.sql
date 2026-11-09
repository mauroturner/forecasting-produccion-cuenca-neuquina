-- Violations: effective days that are negative or above the days of the month.
SELECT well_id, period_key, effective_days, days_in_month
FROM stg_monthly_production
WHERE effective_days < 0 OR effective_days > days_in_month;
