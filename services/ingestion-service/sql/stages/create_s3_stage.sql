-- ============================================================================
-- File Name   : create_s3_stage.sql
-- Description : Creates an External Stage for AWS S3
-- Author      : Team IRM
-- ============================================================================

USE DATABASE {{DATABASE_NAME}};
USE SCHEMA {{SCHEMA_NAME}};

CREATE STAGE IF NOT EXISTS {{STAGE_NAME}}
URL = 's3://{{BUCKET_NAME}}'
CREDENTIALS = (
    AWS_KEY_ID = '{{AWS_ACCESS_KEY_ID}}'
    AWS_SECRET_KEY = '{{AWS_SECRET_ACCESS_KEY}}'
)
FILE_FORMAT = {{FILE_FORMAT}}
COMMENT = 'External Stage for loading CSV files from AWS S3';

SHOW STAGES IN SCHEMA {{SCHEMA_NAME}};