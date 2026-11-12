import os
from pathlib import Path

TEST_ROOT = Path(__file__).resolve().parent / ".runtime"
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["MINUTESTRACE_DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}"
os.environ["MINUTESTRACE_STORAGE_DIR"] = str(TEST_ROOT / "uploads")
os.environ["MINUTESTRACE_JWT_SECRET"] = "test-secret-with-enough-entropy"
os.environ["MINUTESTRACE_LLM_API_KEY"] = ""
os.environ["MINUTESTRACE_DEMO_PASSWORD"] = "demo123456"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def auth(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": "demo", "password": "demo123456"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}
