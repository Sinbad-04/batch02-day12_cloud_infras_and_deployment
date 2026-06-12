"""
Unit tests for the production AI agent.

Run:
    cd 06-lab-complete
    pytest -v --cov=app
"""
import os

# Ensure config validation passes before importing the app.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("AGENT_API_KEY", "test-key")

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)
API_KEY = settings.agent_api_key


def test_root_lists_endpoints():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["app"] == settings.app_name


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_after_startup():
    # TestClient runs lifespan, so the app should be ready.
    with TestClient(app) as c:
        r = c.get("/ready")
        assert r.status_code == 200
        assert r.json()["ready"] is True


def test_ask_requires_api_key():
    r = client.post("/ask", json={"question": "Hello"})
    assert r.status_code == 401


def test_ask_with_valid_key():
    r = client.post(
        "/ask",
        json={"question": "What is Docker?"},
        headers={"X-API-Key": API_KEY},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["question"] == "What is Docker?"
    assert isinstance(body["answer"], str) and body["answer"]


def test_ask_rejects_empty_question():
    r = client.post(
        "/ask",
        json={"question": ""},
        headers={"X-API-Key": API_KEY},
    )
    assert r.status_code == 422  # Pydantic min_length=1


def test_metrics_protected():
    assert client.get("/metrics").status_code == 401
    r = client.get("/metrics", headers={"X-API-Key": API_KEY})
    assert r.status_code == 200
    assert "uptime_seconds" in r.json()
