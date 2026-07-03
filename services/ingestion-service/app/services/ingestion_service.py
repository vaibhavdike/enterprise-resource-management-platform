from pathlib import Path

from app.connectors.snowflake_connector import SnowflakeConnector
from app.config.settings import settings
from app.models.metadata import FILE_TABLE_MAPPING


class IngestionService:
    """
    Orchestrates the complete ingestion service.
    """

    def __init__(self):
        self.connector = SnowflakeConnector()

    def run(self):
        """
        Main execution flow.
        """
        self.initialize_database()
        self.load_data()

        # Uncomment after implementing copy_into_table()
        # self.load_data()

    def initialize_database(self):
        """
        Creates all required Snowflake objects.
        """

        try:
            self.connector.connect()

            print("\n======================================")
            print("Initializing Snowflake Database...")
            print("======================================")

            self.execute_sql_folder("sql/database")
            self.execute_sql_folder("sql/schemas")
            self.execute_sql_folder("sql/file_formats")
            self.execute_sql_folder("sql/stages")
            self.execute_sql_folder("sql/tables")

            print("\n======================================")
            print("Database Initialization Completed")
            print("======================================")

        except Exception as e:
            print(f"\n❌ Initialization Failed: {e}")
            raise

        finally:
            self.connector.close()

    def execute_sql_folder(self, folder_path):
        """
        Executes all SQL files inside a folder.
        """

        folder = Path(folder_path)

        if not folder.exists():
            print(f"⚠ Folder not found: {folder_path}")
            return

        sql_files = sorted(folder.glob("*.sql"))

        if not sql_files:
            print(f"⚠ No SQL files found in {folder_path}")
            return

        print(f"\nExecuting SQL Folder: {folder_path}")

        for sql_file in sql_files:
            print(f"Executing: {sql_file.name}")
            self.connector.execute_sql_file(sql_file)

    def list_stage_files(self):
        """
        Lists all files available in the Snowflake stage.
        """

        try:
            self.connector.connect()

            print("\n======================================")
            print("Files Available in Snowflake Stage")
            print("======================================")

            files = self.connector.list_stage_files(
                settings.SNOWFLAKE_STAGE_NAME
            )

            if not files:
                print("No files found in stage.")
                return

            for file in files:
                print(file)

        except Exception as e:
            print(f"\n❌ Failed to list stage files: {e}")
            raise

        finally:
            self.connector.close()

    def load_data(self):
        """
        Loads all files from the Snowflake stage into RAW tables.
        (Implement after copy_into_table() is ready.)
        """

        try:
            self.connector.connect()

            files = self.connector.list_stage_files(
                settings.SNOWFLAKE_STAGE_NAME
            )

            for file in files:

                # LIST returns the full stage path
                file_name = file["name"].split("/")[-1]

                if file_name not in FILE_TABLE_MAPPING:
                    print(f"Skipping {file_name}")
                    continue

                table_name = FILE_TABLE_MAPPING[file_name]

                print(f"\nLoading {file_name} -> {table_name}")

                self.connector.copy_into_table(
                    table_name=table_name,
                    stage_name=settings.SNOWFLAKE_STAGE_NAME,
                    file_name=file_name,
                )

                print(f"Successfully loaded {table_name}")

        except Exception as e:
            print(f"\n❌ Load Failed: {e}")
            raise

        finally:
            self.connector.close()