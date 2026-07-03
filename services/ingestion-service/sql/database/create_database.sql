-- ==========================================================
-- File        : create_database.sql
-- Description : Creates the IRM database if it does not exist
-- Author      : Team IRM
-- ==========================================================

CREATE DATABASE IF NOT EXISTS {{DATABASE_NAME}}
COMMENT = 'Database for Intelligent Resource Management Platform';