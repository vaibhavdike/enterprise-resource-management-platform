-- ==========================================================
-- Use Database, Schema and Role
-- ==========================================================

USE ROLE SYSADMIN;
USE DATABASE IRM_DB;
USE SCHEMA RAW;

-- ==========================================================
-- Create / Replace Snowpark Container Service
-- ==========================================================

CREATE OR REPLACE SERVICE INGESTION_SERVICE
IN COMPUTE POOL IRM_COMPUTE_POOL
FROM SPECIFICATION $$
spec:
  containers:
    - name: ingestion-service

      image: a4357138117071-accelirate-partner.registry.snowflakecomputing.com/irm_db/raw/irm_image_repository:latest

      command:
        - python

      args:
        - run.py

      env:
        APP_NAME: "Ingestion Service"
        ENV: "DEV"
        LOG_LEVEL: "INFO"

  endpoints:
    - name: ingestion
      port: 8080
      public: false
$$;