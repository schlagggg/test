import pytest
from fastapi.testclient import TestClient

from mensch.api import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app(f"sqlite:///{tmp_path / 'test.db'}", seed_demo=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def users(client):
    return {e["email"].split("@")[0]: e["id"] for e in client.get("/api/employees").json()}


def as_user(user_id: int) -> dict:
    return {"X-User-Id": str(user_id)}
