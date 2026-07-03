-- ============================================================================
-- File Name   : create_raw_schema.sql
-- Description : Creates the RAW schema for the Enterprise Resource
--               Management Platform if it does not already exist.
-- Author      : Team IRM
-- ============================================================================

-- Switch to the target database
USE DATABASE {{DATABASE_NAME}};

-- Create RAW schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS {{SCHEMA_NAME}}
COMMENT = 'Landing zone for raw data ingested from source systems';

-- Set RAW as the active schema
USE SCHEMA {{SCHEMA_NAME}};

