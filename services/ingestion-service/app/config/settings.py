import os
from pathlib import Path
from dotenv import load_dotenv

# Path to .env
BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


class Settings:

    ENV = os.getenv("ENV")

    # AWS
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION")
    AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
    AWS_FILE_PATH = os.getenv("AWS_FILE_PATH")

    # Snowflake
    SNOWFLAKE_ACCOUNT = os.getenv("SNOWFLAKE_ACCOUNT")
    SNOWFLAKE_USER = os.getenv("SNOWFLAKE_USER")
    SNOWFLAKE_PASSWORD = os.getenv("SNOWFLAKE_PASSWORD")
    SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE")
    SNOWFLAKE_DATABASE = os.getenv("SNOWFLAKE_DATABASE")
    SNOWFLAKE_SCHEMA = os.getenv("SNOWFLAKE_SCHEMA")
    SNOWFLAKE_ROLE = os.getenv("SNOWFLAKE_ROLE")
    SNOWFLAKE_STAGE_NAME = os.getenv("SNOWFLAKE_STAGE_NAME")
    SNOWFLAKE_FILE_FORMAT = os.getenv("SNOWFLAKE_FILE_FORMAT")

    # Logging
    LOG_LEVEL = os.getenv("LOG_LEVEL")
    LOG_PATH = os.getenv("LOG_PATH")

    APP_NAME = os.getenv("APP_NAME")


settings = Settings()