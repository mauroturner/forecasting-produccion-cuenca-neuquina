-- The six methods that are compared (docs/plan.md, sections 9 and 13).
DROP TABLE IF EXISTS dim_method;

CREATE TABLE dim_method AS
SELECT 'naive_last' AS method_key, 'Repetir el último mes' AS method_name_es, 'Línea base' AS family,
       'Repite la tasa por día del último mes.' AS description_es, 1 AS is_base, 1 AS sort_order
UNION ALL
SELECT 'naive_mean3', 'Promedio de 3 meses', 'Línea base',
       'Promedia la tasa por día de los últimos 3 meses.', 1, 2
UNION ALL
SELECT 'arps_exp', 'Arps exponencial', 'Arps',
       'Curva de declinación exponencial ajustada al segmento posterior al pico.', 0, 3
UNION ALL
SELECT 'arps_mh_b2', 'Arps hiperbólica modificada (b hasta 2)', 'Arps',
       'Caso base: hiperbólica con b entre 0,001 y 2 y declinación terminal de 10 % efectivo anual.', 0, 4
UNION ALL
SELECT 'arps_mh_b1', 'Arps hiperbólica modificada (b hasta 1)', 'Arps',
       'Sensibilidad: la misma curva con b entre 0,001 y 1.', 0, 5
UNION ALL
SELECT 'ml_hgb', 'Machine learning (gradient boosting)', 'Machine learning',
       'Gradient boosting con pérdida cuantílica (P10, P50, P90), entrenado con todos los pozos.', 0, 6;
