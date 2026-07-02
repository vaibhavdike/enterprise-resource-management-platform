"""Placeholder ingestion service."""


class IngestionService:
    """Simple placeholder service."""

    def process(self, payload: dict) -> dict:
        return {"status": "received", "payload": payload}
