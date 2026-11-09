-- Violations: a company_key that appears more than once, or is NULL, in dim_company.
SELECT company_key, COUNT(*) AS n_rows
FROM dim_company
GROUP BY company_key
HAVING COUNT(*) > 1 OR company_key IS NULL;
