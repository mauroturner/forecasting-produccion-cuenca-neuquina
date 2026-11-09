-- The result of every validation rule in every run. status: pasa, falla (a blocking rule that failed) or advierte.
DROP TABLE IF EXISTS fact_validation;

CREATE TABLE fact_validation AS
SELECT
    v.run_key,
    v.rule_id,
    v.name_es,
    v.severity,
    CASE WHEN v.passed = 1 THEN 'pasa' WHEN v.severity = 'bloqueante' THEN 'falla' ELSE 'advierte' END AS status,
    v.rows_affected,
    v.wells_affected
FROM validation_results AS v
ORDER BY v.run_key, v.rule_id;
