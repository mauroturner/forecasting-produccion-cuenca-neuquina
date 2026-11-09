-- Violations: a well_key that appears more than once in dim_well.
SELECT well_key, COUNT(*) AS n_rows
FROM dim_well
GROUP BY well_key
HAVING COUNT(*) > 1;
