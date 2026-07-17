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


def test_analytics_page(client):
    resp = client.get("/analytics")
    assert resp.status_code == 200
    assert b"chart" in resp.data.lower()


def test_emails_page(client):
    resp = client.get("/emails")
    assert resp.status_code == 200


def test_logs_page_missing_file_is_handled(client):
    resp = client.get("/logs")
    assert resp.status_code == 200


@pytest.fixture
def enriched_client(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://a/1", "p"),
        Job("Abbvie", "QC Analyst", "https://a/2", "p"),
    ], "2026-07-17T10:00:00")
    id1 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/1",)).fetchone()["id"]
    id2 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/2",)).fetchone()["id"]
    storage.save_enrichment(conn, id1, "Needs SAP.", "Senior", [("SAP", "Software")], "2026-07-17T11:00:00")
    storage.save_enrichment(conn, id2, "QC role.", None, [], "2026-07-17T11:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "e.db")
    app.config["TESTING"] = True
    return app.test_client()


def test_new_analytics_api_endpoints_return_json(enriched_client):
    for path in ("/api/top-skills", "/api/seniority-breakdown", "/api/skills-by-category"):
        resp = enriched_client.get(path)
        assert resp.status_code == 200
        assert resp.is_json


def test_drilldown_by_company(enriched_client):
    resp = enriched_client.get("/api/drilldown/company?value=Abbvie")
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.get_json()}
    assert titles == {"SAP Engineer", "QC Analyst"}


def test_drilldown_by_skill(enriched_client):
    resp = enriched_client.get("/api/drilldown/skill?value=SAP")
    titles = {r["title"] for r in resp.get_json()}
    assert titles == {"SAP Engineer"}


def test_drilldown_by_seniority(enriched_client):
    resp = enriched_client.get("/api/drilldown/seniority?value=Senior")
    assert {r["title"] for r in resp.get_json()} == {"SAP Engineer"}

    resp_unspecified = enriched_client.get("/api/drilldown/seniority?value=Unspecified")
    assert {r["title"] for r in resp_unspecified.get_json()} == {"QC Analyst"}


def test_drilldown_by_category(enriched_client):
    resp = enriched_client.get("/api/drilldown/category?value=Quality")
    assert "QC Analyst" in {r["title"] for r in resp.get_json()}


def test_drilldown_unknown_dimension_returns_400(enriched_client):
    resp = enriched_client.get("/api/drilldown/bogus?value=x")
    assert resp.status_code == 400


def test_drilldown_company_respects_row_cap(tmp_path):
    conn = storage.connect(tmp_path / "cap.db")
    jobs = [Job("BigCo", f"Role {i}", f"https://x/{i}", "p") for i in range(150)]
    storage.record_company_snapshot(conn, "BigCo", jobs, "2026-07-17T10:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "cap.db")
    app.config["TESTING"] = True
    resp = app.test_client().get("/api/drilldown/company?value=BigCo")
    assert len(resp.get_json()) == 100
