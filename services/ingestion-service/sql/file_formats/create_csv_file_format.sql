-- ============================================================================
-- File Name   : create_csv_file_format.sql
-- Description : Creates a CSV file format for loading data from AWS S3
--               into Snowflake.
-- Author      : Team IRM
-- ============================================================================

USE DATABASE IRM_DB;
USE SCHEMA RAW;

CREATE FILE FORMAT IF NOT EXISTS {{FILE_FORMAT}}
TYPE = CSV
FIELD_DELIMITER = ','
SKIP_HEADER = 1
FIELD_OPTIONALLY_ENCLOSED_BY = '"'
EMPTY_FIELD_AS_NULL = TRUE
NULL_IF = ('NULL', '', 'null')
TRIM_SPACE = TRUE
ERROR_ON_COLUMN_COUNT_MISMATCH = FALSE
REPLACE_INVALID_CHARACTERS = TRUE
ENCODING = 'UTF8';

