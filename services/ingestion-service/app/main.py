from app.services.ingestion_service import IngestionService


def main():
    ingestion = IngestionService()
    ingestion.run()


if __name__ == "__main__":
    main()