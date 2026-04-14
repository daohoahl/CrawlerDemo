from fastapi.testclient import TestClient
from crawlerdemo.web import app
from crawlerdemo.db import make_engine, init_db
from crawlerdemo.config import get_settings

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}

def test_crawl_status():
    response = client.get("/api/crawl/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "last_started_at" in data
    
def test_dashboard_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Crawler Dashboard" in response.text
