# Airflow with the libraries of the pipeline. The official pattern: reinstall apache-airflow at the same version
# so that pip never changes it while it resolves the other packages.
FROM apache/airflow:3.4.0

ARG AIRFLOW_VERSION=3.4.0
COPY requirements-airflow.txt /requirements-airflow.txt
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" -r /requirements-airflow.txt
