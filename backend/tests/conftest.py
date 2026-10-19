
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Set a test-only key; tests must not make real AI requests.
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key-not-used")

    import database

    # Redirect database.py to a fresh, temporary SQLite database.
    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "test_stratify.db",
    )

    # Import after patching the database path.
    import main

    with TestClient(main.app) as test_client:
        yield test_client
