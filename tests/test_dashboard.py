import pytest

from jobfinder import storage
from jobfinder.models import Job


@pytest.fixture
def client(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "QC Analyst", "https://a/1", "p"),
    ], "2026-07-05T10:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "t.db")
    app.config["TESTING"] = True
    return app.test_client()


def test_overview_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"QC Analyst" not in resp.data  # overview shows stats, not job rows
    assert b"Active jobs" in resp.data


def test_jobs_page_lists_and_filters(client):
    resp = client.get("/jobs")
    assert b"QC Analyst" in resp.data
    resp = client.get("/jobs?company=Amgen")
    assert b"QC Analyst" not in resp.data
    resp = client.get("/jobs?q=analyst")
    assert b"QC Analyst" in resp.data


def test_api_endpoints_return_json(client):
    for path in ("/api/jobs-per-company", "/api/new-per-week", "/api/categories"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.is_json
