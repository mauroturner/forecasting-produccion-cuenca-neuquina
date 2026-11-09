-- Violations: a month of dim_calendar whose next month is missing (a gap in period_index), or a
-- period_key repeated.
SELECT a.period_index
FROM dim_calendar AS a
WHERE a.period_index < (SELECT MAX(period_index) FROM dim_calendar)
  AND NOT EXISTS (SELECT 1 FROM dim_calendar AS b WHERE b.period_index = a.period_index + 1)
UNION ALL
SELECT period_index
FROM dim_calendar
GROUP BY period_key
HAVING COUNT(*) > 1;
