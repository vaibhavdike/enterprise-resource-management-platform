from pathlib import Path

import snowflake.connector
from snowflake.connector import DictCursor

from app.config.settings import settings


class SnowflakeConnector:
    """
    Handles Snowflake connection and query execution.
    """

    def __init__(self):
        self.connection = None

    def connect(self):
        """
        Establish a connection to Snowflake.
        """
        try:
            if self.connection is None or self.connection.is_closed():
                self.connection = snowflake.connector.connect(
                    account=settings.SNOWFLAKE_ACCOUNT,
                    user=settings.SNOWFLAKE_USER,
                    password=settings.SNOWFLAKE_PASSWORD,
                    warehouse=settings.SNOWFLAKE_WAREHOUSE,
                    database=settings.SNOWFLAKE_DATABASE,
                    schema=settings.SNOWFLAKE_SCHEMA,
                    role=settings.SNOWFLAKE_ROLE,
                )

                print("✅ Successfully connected to Snowflake.")

            return self.connection

        except Exception as e:
            print(f"❌ Failed to connect to Snowflake: {e}")
            raise

    def execute_query(self, query):
        """
        Execute any SQL query.
        """

        if self.connection is None:
            self.connect()

        try:
            cursor = self.connection.cursor(DictCursor)

            cursor.execute(query)

            try:
                result = cursor.fetchall()
            except Exception:
                result = None

            cursor.close()

            return result

        except Exception as e:
            print(f"❌ Query execution failed: {e}")
            raise

    def execute_sql_file(self, file_path):
        """
        Execute all SQL statements from a SQL file.
        """

        if self.connection is None:
            self.connect()

        try:
            sql_path = Path(file_path)

            with open(sql_path, "r", encoding="utf-8") as file:
                sql = file.read()

            sql = (
                sql.replace("{{DATABASE_NAME}}", settings.SNOWFLAKE_DATABASE)
                .replace("{{SCHEMA_NAME}}", settings.SNOWFLAKE_SCHEMA)
                .replace("{{STAGE_NAME}}", settings.SNOWFLAKE_STAGE_NAME)
                .replace("{{BUCKET_NAME}}", settings.AWS_BUCKET_NAME)
                .replace("{{AWS_ACCESS_KEY_ID}}", settings.AWS_ACCESS_KEY_ID)
                .replace("{{AWS_SECRET_ACCESS_KEY}}", settings.AWS_SECRET_ACCESS_KEY)
                .replace("{{FILE_FORMAT}}", settings.SNOWFLAKE_FILE_FORMAT)
            )

            statements = [
                stmt.strip()
                for stmt in sql.split(";")
                if stmt.strip()
            ]

            cursor = self.connection.cursor()

            for statement in statements:
                cursor.execute(statement)

            cursor.close()

            print(f"✅ Executed SQL file: {sql_path.name}")

        except Exception as e:
            print(f"❌ Failed to execute {file_path}: {e}")
            raise

    def list_stage_files(self, stage_name):
        """
        List all files available in the Snowflake stage.
        """

        if self.connection is None:
            self.connect()

        query = f"LIST @{stage_name};"

        try:
            cursor = self.connection.cursor(DictCursor)

            cursor.execute(query)

            files = cursor.fetchall()

            cursor.close()

            return files

        except Exception as e:
            print(f"❌ Failed to list stage files: {e}")
            raise

    def copy_into_table(self, table_name, stage_name, file_name):
        """
        Load a CSV file from Snowflake Stage into a table.
        """

        if self.connection is None:
            self.connect()

        query = f"""
        COPY INTO {settings.SNOWFLAKE_DATABASE}.{settings.SNOWFLAKE_SCHEMA}.{table_name}
        FROM @{stage_name}/{file_name}
        FILE_FORMAT = (
            FORMAT_NAME = '{settings.SNOWFLAKE_DATABASE}.{settings.SNOWFLAKE_SCHEMA}.{settings.SNOWFLAKE_FILE_FORMAT}'
        )
        ON_ERROR = CONTINUE;
        """

        try:
            cursor = self.connection.cursor(DictCursor)

            cursor.execute(query)

            result = cursor.fetchall()

            cursor.close()

            return result

        except Exception as e:
            print(f"❌ Failed to load {file_name}: {e}")
            raise

    def close(self):
        """
        Close Snowflake connection.
        """

        if self.connection:
            self.connection.close()
            self.connection = None
            print("✅ Snowflake connection closed.")