-- The base curve over the fitted months of the latest origin.
DROP TABLE IF EXISTS fact_fitted_curve;

CREATE TABLE fact_fitted_curve AS
SELECT
    c.well_id AS well_key,
    c.fluid   AS fluid_key,
    c.period_key,
    c.origin_period_key,
    c.fitted_volume
FROM model_fitted_curve AS c
ORDER BY c.well_id, c.fluid, c.period_key;
