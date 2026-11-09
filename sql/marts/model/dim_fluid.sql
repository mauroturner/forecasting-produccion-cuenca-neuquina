-- The two fluids that are forecast. They are never added together.
DROP TABLE IF EXISTS dim_fluid;

CREATE TABLE dim_fluid AS
SELECT 'oil' AS fluid_key, 'Petróleo' AS fluid_name_es, 'm³' AS unit
UNION ALL
SELECT 'gas', 'Gas', 'miles de m³';
