-- Violations: a key that appears more than once in a model dimension.
SELECT 'dim_fluid' AS dimension, fluid_key AS duplicated_key FROM dim_fluid GROUP BY fluid_key HAVING COUNT(*) > 1
UNION ALL
SELECT 'dim_method', method_key FROM dim_method GROUP BY method_key HAVING COUNT(*) > 1
UNION ALL
SELECT 'dim_horizon', horizon FROM dim_horizon GROUP BY horizon HAVING COUNT(*) > 1
UNION ALL
SELECT 'dim_origin', origin_period_key FROM dim_origin GROUP BY origin_period_key HAVING COUNT(*) > 1
UNION ALL
SELECT 'dim_pipeline_run', run_key FROM dim_pipeline_run GROUP BY run_key HAVING COUNT(*) > 1;
