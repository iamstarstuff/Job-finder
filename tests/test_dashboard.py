from datetime import datetime, timedelta

import pytest

from jobfinder import storage
from jobfinder.models import Job
from dashboard import charts
from tests.conftest import save_reading


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
    assert b"Open roles" in resp.data


def test_jobs_page_lists_and_filters(client):
    resp = client.get("/jobs")
    assert b"QC Analyst" in resp.data
    resp = client.get("/jobs?company=Amgen")
    assert b"QC Analyst" not in resp.data
    resp = client.get("/jobs?q=analyst")
    assert b"QC Analyst" in resp.data


def test_emails_page(client):
    resp = client.get("/emails")
    assert resp.status_code == 200


def test_logs_page_missing_file_is_handled(client):
    resp = client.get("/logs")
    assert resp.status_code == 200


@pytest.fixture
def enriched_client(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    sap = Job("Abbvie", "SAP Engineer", "https://a/1", "p")
    qc = Job("Abbvie", "QC Analyst", "https://a/2", "p")
    storage.record_company_snapshot(conn, "Abbvie", [sap, qc], "2026-07-17T10:00:00")
    save_reading(conn, sap, role_family="Engineering", seniority="Senior", skills=["SAP"])
    save_reading(conn, qc, role_family="Quality", skills=["GMP"])
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "e.db")
    app.config["TESTING"] = True
    return app.test_client()


def test_drilldown_by_skill_is_case_insensitive(enriched_client):
    resp = enriched_client.get("/api/drilldown/skill?value=sap")
    assert {r["title"] for r in resp.get_json()} == {"SAP Engineer"}


def test_drilldown_by_seniority(enriched_client):
    resp = enriched_client.get("/api/drilldown/seniority?value=Senior")
    assert {r["title"] for r in resp.get_json()} == {"SAP Engineer"}
    resp = enriched_client.get("/api/drilldown/seniority?value=Not+stated")
    assert {r["title"] for r in resp.get_json()} == {"QC Analyst"}


def test_drilldown_by_role_family_and_company_family(enriched_client):
    resp = enriched_client.get("/api/drilldown/role_family?value=Quality")
    assert {r["title"] for r in resp.get_json()} == {"QC Analyst"}
    resp = enriched_client.get("/api/drilldown/company_family?value=Abbvie::Engineering")
    assert {r["title"] for r in resp.get_json()} == {"SAP Engineer"}


def test_drilldown_respects_weeks_and_rejects_bad_windows(enriched_client):
    assert enriched_client.get("/api/drilldown/skill?value=SAP&weeks=4").get_json() == []  # July is long gone
    assert enriched_client.get("/api/drilldown/skill?value=SAP&weeks=5").status_code == 400


def test_drilldown_by_category_is_gone(enriched_client):
    assert enriched_client.get("/api/drilldown/category?value=Quality").status_code == 400


def test_drilldown_by_company(enriched_client):
    resp = enriched_client.get("/api/drilldown/company?value=Abbvie")
    assert resp.status_code == 200
    titles = {r["title"] for r in resp.get_json()}
    assert titles == {"SAP Engineer", "QC Analyst"}


def test_drilldown_unknown_dimension_returns_400(enriched_client):
    resp = enriched_client.get("/api/drilldown/bogus?value=x")
    assert resp.status_code == 400


def test_logs_page_defaults_to_pharma_log(client):
    resp = client.get("/logs")
    assert resp.status_code == 200


def test_logs_page_accepts_tech_and_enrichment(client):
    for log_name in ("tech", "enrichment"):
        resp = client.get(f"/logs?log={log_name}")
        assert resp.status_code == 200


def test_logs_page_has_links_to_switch_logs(client):
    resp = client.get("/logs")
    assert b'href="/logs?log=tech"' in resp.data
    assert b'href="/logs?log=enrichment"' in resp.data


def test_jobs_page_sector_filter(client):
    resp = client.get("/jobs?sector=tech")
    assert b"QC Analyst" not in resp.data
    resp = client.get("/jobs?sector=pharma")
    assert b"QC Analyst" in resp.data


def test_landing_page_links_to_both_sector_pages(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'href="/sector/pharma"' in resp.data
    assert b'href="/sector/tech"' in resp.data


def test_landing_page_no_longer_shows_per_company_table(client):
    resp = client.get("/")
    assert b"Jobs per company" not in resp.data


def test_sector_page_pharma_shows_only_pharma_data(client):
    resp = client.get("/sector/pharma")
    assert resp.status_code == 200
    assert b"QC Analyst" in resp.data


def test_sector_page_tech_shows_no_pharma_jobs(client):
    resp = client.get("/sector/tech")
    assert resp.status_code == 200
    assert b"QC Analyst" not in resp.data


def test_sector_page_rejects_invalid_name(client):
    resp = client.get("/sector/nonsense")
    assert resp.status_code == 404


def test_api_drilldown_company_respects_sector_filter(enriched_client):
    resp = enriched_client.get("/api/drilldown/company?value=Abbvie&sector=tech")
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_api_drilldown_company_without_sector_is_unfiltered(enriched_client):
    resp = enriched_client.get("/api/drilldown/company?value=Abbvie")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 2


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


@pytest.fixture
def jobs_search_client(tmp_path):
    conn = storage.connect(tmp_path / "s.db")
    storage.record_company_snapshot(conn, "BMS", [
        Job("BMS", "Data Platform Engineer", "https://a/1", "p"),
        Job("BMS", "QC Analyst", "https://a/2", "p"),
    ], "2026-07-17T10:00:00")
    id1 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/1",)).fetchone()["id"]
    id2 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/2",)).fetchone()["id"]
    storage.save_enrichment(
        conn, id1, "Experience orchestrating pipelines with Airflow and dbt. SQL required.",
        "Senior", [("SQL", "Software")], "2026-07-17T11:00:00",
    )
    storage.save_enrichment(conn, id2, "QC role, GMP required.", None, [], "2026-07-17T11:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "s.db")
    app.config["TESTING"] = True
    return app.test_client()


def test_jobs_page_skill_search_filters_by_description(jobs_search_client):
    resp = jobs_search_client.get("/jobs?skill=airflow")
    assert b"Data Platform Engineer" in resp.data
    assert b"QC Analyst" not in resp.data


def test_jobs_page_skill_search_combines_with_company_filter(jobs_search_client):
    resp = jobs_search_client.get("/jobs?skill=airflow&company=BMS")
    assert b"Data Platform Engineer" in resp.data
    resp2 = jobs_search_client.get("/jobs?skill=airflow&company=Astellas")
    assert b"Data Platform Engineer" not in resp2.data


def test_jobs_page_skill_search_excludes_unenriched_jobs(tmp_path):
    conn = storage.connect(tmp_path / "n.db")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "Warehouse Lead", "https://a/1", "p"),
    ], "2026-07-17T10:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "n.db")
    app.config["TESTING"] = True
    resp = app.test_client().get("/jobs?skill=airflow")
    assert b"Warehouse Lead" not in resp.data


def test_highlight_escapes_html_and_wraps_match():
    from dashboard.app import highlight
    result = highlight("Needs <b>Airflow</b> experience", "airflow")
    assert str(result) == "Needs &lt;b&gt;Airflow&lt;/b&gt; experience".replace(
        "Airflow", "<mark>Airflow</mark>"
    )


def test_highlight_returns_escaped_text_when_no_term():
    from dashboard.app import highlight
    result = highlight("Needs <b>Airflow</b>", "")
    assert str(result) == "Needs &lt;b&gt;Airflow&lt;/b&gt;"


def test_jobs_page_shows_description_and_skills(jobs_search_client):
    resp = jobs_search_client.get("/jobs")
    assert b"Airflow" in resp.data
    assert b"SQL" in resp.data


def test_jobs_page_shows_placeholder_for_unenriched_job(tmp_path):
    conn = storage.connect(tmp_path / "u.db")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "Warehouse Lead", "https://a/1", "p"),
    ], "2026-07-17T10:00:00")
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "u.db")
    app.config["TESTING"] = True
    resp = app.test_client().get("/jobs")
    assert b"Description not available yet" in resp.data


def test_jobs_page_row_markup_unchanged_after_macro_extraction(client):
    resp = client.get("/jobs")
    assert b'class="job-row"' in resp.data
    assert b'class="job-row-summary"' in resp.data


def test_api_chart_returns_the_contract(client):
    resp = client.get("/api/charts/skills-in-demand")
    assert resp.status_code == 200 and resp.is_json
    body = resp.get_json()
    assert set(body) == {"option", "columns", "rows", "drilldown", "height"}
    assert body["columns"] == ["Skill", "Roles"]


def test_api_chart_unknown_name_is_404(client):
    assert client.get("/api/charts/nope").status_code == 404


def test_api_chart_rejects_windows_outside_the_spec(client):
    assert client.get("/api/charts/skills-in-demand?weeks=5").status_code == 400
    assert client.get("/api/charts/skills-in-demand?weeks=abc").status_code == 400
    for weeks in (0, 4, 12, 26):
        assert client.get(f"/api/charts/skills-in-demand?weeks={weeks}").status_code == 200


def test_api_chart_threads_sector_and_weeks_to_the_builder(client, monkeypatch):
    calls = []

    def fake(conn, sector, weeks, now=None):
        calls.append((sector, weeks))
        return charts._empty(["A"])

    monkeypatch.setitem(charts.CHARTS, "skills-in-demand", fake)
    client.get("/api/charts/skills-in-demand?sector=tech&weeks=4")
    client.get("/api/charts/skills-in-demand?sector=bogus")
    assert calls == [("tech", 4), (None, 12)]


def test_analytics_redirects_home(client):
    resp = client.get("/analytics")
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_base_layout_has_wordmark_font_and_new_nav(client):
    html = client.get("/").data.decode()
    assert "Bricolage+Grotesque" in html
    assert '<a class="wordmark" href="/">Job Finder</a>' in html
    for href in ("/sector/pharma", "/sector/tech", "/jobs", "/health", "/emails", "/logs"):
        assert f'href="{href}"' in html
    assert ">Analytics<" not in html
    assert "chart.js" not in html


def test_charts_js_is_served_and_never_uses_innerhtml(client):
    resp = client.get("/static/charts.js")
    assert resp.status_code == 200
    js = resp.data.decode()
    assert "echarts.init" in js
    assert "textContent" in js
    assert "innerHTML" not in js


def test_chart_card_macro_renders_the_mount_points(client):
    from flask import render_template_string
    app = client.application
    with app.app_context():
        html = render_template_string(
            '{% from "_charts.html" import chart_card %}'
            '{% call chart_card("who-is-hiring", "Who is hiring", "Companies by open roles", 6, "pharma", 12) %}'
            '<p class="movers-test">extra</p>{% endcall %}')
    assert 'data-chart="who-is-hiring"' in html and 'data-sector="pharma"' in html and 'data-weeks="12"' in html
    assert 'class="chart-card span-6"' in html
    assert "<h3>Who is hiring</h3>" in html and "Companies by open roles" in html
    assert 'class="chart"' in html and 'class="drilldown" hidden' in html
    assert "<summary>Show data</summary>" in html and 'class="chart-table table-scroll"' in html
    assert '<p class="movers-test">extra</p>' in html


def test_chart_card_macro_defaults_sector_and_weeks_safely(client):
    from flask import render_template_string
    app = client.application
    with app.app_context():
        html = render_template_string(
            '{% from "_charts.html" import chart_card %}'
            '{% call chart_card("skill-trend", "Skill trend", "", 6, None, 0) %}'
            '{% endcall %}')
    assert 'data-sector=""' in html
    assert 'data-weeks="0"' in html


def test_charts_js_surfaces_drilldown_fetch_failures(client):
    resp = client.get("/static/charts.js")
    assert resp.status_code == 200
    js = resp.data.decode()
    assert "echarts.init" in js
    assert "textContent" in js
    assert "innerHTML" not in js
    assert "Could not load the roles behind this value." in js


def test_home_renders_filters_brief_tiles_and_chart_mounts(client):
    html = client.get("/").data.decode()
    assert '<select name="weeks"' in html and '<select name="sector"' in html
    assert "This week in Irish pharma and tech hiring" in html
    assert ("landed this week" in html) or ("No new roles have landed this week yet." in html)
    for label in ("Open roles", "New this week", "Companies tracked", "Roles with full descriptions"):
        assert label in html
    for name in ("skills-in-demand", "hiring-velocity", "who-is-hiring", "skill-trend"):
        assert f'data-chart="{name}"' in html
    assert 'data-chart="seniority-mix"' not in html
    assert "echarts@5/dist/echarts.min.js" in html and "charts.js" in html
    assert "chart.js@4" not in html


def test_home_threads_window_and_sector_into_cards_and_rejects_bad_window(client):
    html = client.get("/?weeks=4&sector=tech").data.decode()
    assert 'data-weeks="4"' in html and 'data-sector="tech"' in html
    assert '<option value="4" selected>' in html
    assert '<option value="tech" selected>' in html
    assert client.get("/?weeks=7").status_code == 400


def test_home_shows_movers_for_windows_but_not_all_time(client):
    assert "Rising" in client.get("/?weeks=12").data.decode()
    assert "Rising" not in client.get("/?weeks=0").data.decode()


def test_home_movers_note_when_previous_window_has_no_data(tmp_path):
    # Seed the single job relative to the real clock (not a fixed calendar
    # date) so it always falls inside the current 12-week window and the
    # previous window (weeks 13-24 ago) is always empty: nothing to compare.
    conn = storage.connect(tmp_path / "movers.db")
    seeded_at = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "QC Analyst", "https://a/1", "p"),
    ], seeded_at)
    conn.close()
    from dashboard.app import create_app
    app = create_app(db_path=tmp_path / "movers.db")
    app.config["TESTING"] = True
    movers_client = app.test_client()

    html = movers_client.get("/?weeks=12").data.decode()
    assert "Not enough history to compare with the previous window yet" in html
    assert "▲" not in html


def test_sector_page_has_the_extra_charts_recent_jobs_and_no_sector_select(client):
    html = client.get("/sector/pharma").data.decode()
    for name in ("skills-in-demand", "hiring-velocity", "who-is-hiring", "skill-trend",
                 "seniority-mix", "company-families", "days-to-close"):
        assert f'data-chart="{name}"' in html
    assert "This week in Irish pharma hiring" in html
    assert 'data-sector="pharma"' in html
    assert '<select name="sector"' not in html and '<select name="weeks"' in html
    assert "QC Analyst" in html            # recent-jobs list
    assert "See all 1 jobs" in html and "→" not in html


def test_old_chart_api_routes_are_gone(client):
    for path in ("/api/jobs-per-company", "/api/new-per-week", "/api/categories",
                 "/api/top-skills", "/api/seniority-breakdown", "/api/skills-by-category"):
        assert client.get(path).status_code == 404, path


def test_health_page_renders_every_status_runs_and_email_stats(tmp_path):
    conn = storage.connect(tmp_path / "h.db")
    for company, sector in (("Pfizer", "pharma"), ("Astellas", "pharma"),
                            ("Leo Pharma", "pharma"), ("Johnson & Johnson", "pharma")):
        storage.record_company_snapshot(conn, company, [
            Job(company, "Role", f"https://{company}/1", "p", sector=sector),
        ], "2026-09-14T10:00:00")
    storage.sync_company_failures(conn, "pharma", {
        "Astellas": "404 Client Error: Not Found",
        "Leo Pharma": "returned 0 jobs but previously had active listings",
    })
    run_id = storage.start_run(conn, "2026-09-15T16:00:00", "pharma")
    storage.finish_run(conn, run_id, "2026-09-15T16:00:21", 355, 0, {"Astellas": "404"})
    storage.log_email(conn, "2026-09-15T16:00:30", "alert", "3 New Job Postings", ["x@example.com"], True)
    conn.close()
    from dashboard.app import create_app
    client = create_app(db_path=tmp_path / "h.db").test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    html = resp.data.decode()
    for label in ("! Failing", "○ Empty listing", "– Retired", "✓ OK"):
        assert label in html, label
    assert "404 Client Error" in html
    assert "Johnson &amp; Johnson" in html
    assert html.index("Astellas") < html.index("Pfizer")   # problems first
    assert "21 s" in html and "1/1" in html and "alert delivered" in html


def test_emails_page_uses_tiles_and_sentence_case(client):
    html = client.get("/emails").data.decode()
    assert "<h2>Emails</h2>" in html
    assert 'class="cards"' not in html


def test_jobs_and_logs_headings_are_sentence_case(client):
    assert "<h2>Jobs</h2>" in client.get("/jobs").data.decode()
    assert "<h2>Logs</h2>" in client.get("/logs").data.decode()


def test_health_page_shows_the_claude_api_panel(tmp_path):
    conn = storage.connect(tmp_path / "c.db")
    now = datetime.now().isoformat(timespec="seconds")
    row = dict.fromkeys(storage.INSIGHT_COLUMNS)
    row.update(job_key="https://t/1", sector="tech", company="T", title="ML Engineer", status="ok",
               title_only=0, model="claude-sonnet-5-5", prompt_version=1, input_tokens=2000,
               output_tokens=300, cost_usd=0.0123, via_batch=0, classified_at=now)
    storage.save_insight(conn, row)
    storage.sync_company_failures(conn, "insights", {"Claude API": "401 invalid x-api-key"})
    conn.close()
    from dashboard.app import create_app
    html = create_app(db_path=tmp_path / "c.db").test_client().get("/health").data.decode()
    assert "Claude API" in html
    assert "$0.01" in html and "1/200" in html
    assert "401 invalid x-api-key" in html


def test_health_page_claude_panel_without_data(tmp_path):
    storage.connect(tmp_path / "e.db").close()
    from dashboard.app import create_app
    html = create_app(db_path=tmp_path / "e.db").test_client().get("/health").data.decode()
    assert "Claude API" in html and "$0.00" in html and "0/200" in html


def test_charts_js_supports_cell_drilldowns_card_params_and_notes(client):
    js = client.get("/static/charts.js").data.decode()
    assert 'drilldown.key === "cell"' in js
    assert "select[data-param]" in js
    assert "payload.note" in js
    assert 'params.set("weeks"' in js or "weeks:" in js
