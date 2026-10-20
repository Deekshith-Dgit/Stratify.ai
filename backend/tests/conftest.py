import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-only-key-not-used")

    import database

    monkeypatch.setattr(
        database,
        "DB_PATH",
        tmp_path / "test_stratify.db",
    )

    import main

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def signup_account(client):
    def create_account(username, password="TestPassword123!", name="Test User"):
        response = client.post(
            "/auth/signup",
            json={
                "username": username,
                "password": password,
                "name": name,
            },
        )
        assert response.status_code == 201, response.text
        return response

    return create_account
