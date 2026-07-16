from jobfinder import enrichment
from jobfinder import storage
from jobfinder.models import Job
from tests.conftest import FakeSession, FakeResponse


LDJSON_HTML = """<html><head>
<script type="application/ld+json">
{"@type": "JobPosting", "title": "QC Analyst",
 "description": "<p>We need <strong>SAP</strong> and GMP experience.</p>"}
</script>
</head><body></body></html>"""

LDJSON_NON_JOBPOSTING = """<script type="application/ld+json">
{"@type": "Organization", "name": "Acme"}
</script>"""

LDJSON_MALFORMED = '<script type="application/ld+json">{not valid json}</script>'

LDJSON_NO_DESCRIPTION = """<script type="application/ld+json">
{"@type": "JobPosting", "title": "QC Analyst"}
</script>"""


def test_extract_ldjson_description_strips_html_tags():
    assert enrichment.extract_ldjson_description(LDJSON_HTML) == "We need SAP and GMP experience."


def test_extract_ldjson_description_returns_none_for_non_jobposting():
    assert enrichment.extract_ldjson_description(LDJSON_NON_JOBPOSTING) is None


def test_extract_ldjson_description_skips_malformed_json():
    assert enrichment.extract_ldjson_description(LDJSON_MALFORMED) is None


def test_extract_ldjson_description_returns_none_when_no_script_tag():
    assert enrichment.extract_ldjson_description("<html><body>No JSON-LD here.</body></html>") is None


def test_extract_ldjson_description_returns_none_when_description_missing():
    assert enrichment.extract_ldjson_description(LDJSON_NO_DESCRIPTION) is None


def test_extract_seniority_tiers():
    assert enrichment.extract_seniority("Senior Quality Investigation Engineer") == "Senior"
    assert enrichment.extract_seniority("Site Analytical Sciences Associate Principal Scientist") == "Lead"
    assert enrichment.extract_seniority("Director, Global Compound Market Access") == "Director"
    assert enrichment.extract_seniority("Graduate Programme - Manufacturing") == "Junior"
    assert enrichment.extract_seniority("Technology Engineer - SAP Supply Chain") is None


def test_extract_skills_matches_multiple_and_dedupes_category():
    desc = ("Adheres to Good Manufacturing Practices and Standard Operating Procedures. "
            "Uses SAP, Trackwise and Veeva Vault to manage batch records.")
    names = {name for name, _ in enrichment.extract_skills(desc)}
    assert names == {"GMP", "SOP", "SAP", "Trackwise", "Veeva Vault"}


def test_extract_skills_no_match_returns_empty_list():
    assert enrichment.extract_skills("A lovely day for a walk in the park.") == []


def test_extract_skills_returns_category_alongside_name():
    result = enrichment.extract_skills("Requires strong Python and SQL skills.")
    assert ("Python", "Software") in result
    assert ("SQL", "Software") in result


BMS_STYLE_HTML = ("<script type=\"application/ld+json\">"
                   '{"@type": "JobPosting", "description": '
                   '"Adheres to GMP and uses SAP and Trackwise."}'
                   "</script>").encode()


def test_fetch_description_parses_ldjson_from_response():
    session = FakeSession({"https://example.com/job/1": FakeResponse(content=BMS_STYLE_HTML)})
    result = enrichment.fetch_description(session, "https://example.com/job/1")
    assert result == "Adheres to GMP and uses SAP and Trackwise."


def test_fetch_description_returns_none_when_no_ldjson():
    session = FakeSession({"https://example.com/job/2": FakeResponse(content=b"<html>JS shell</html>")})
    assert enrichment.fetch_description(session, "https://example.com/job/2") is None


def test_run_enriches_new_jobs_and_isolates_failures(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "Senior SAP Engineer", "https://example.com/job/1", "https://example.com/careers"),
        Job("Abbvie", "Unreachable Job", "https://example.com/job/missing", "https://example.com/careers"),
        Job("Abbvie", "No JSON-LD Job", "https://example.com/job/no-ldjson", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")

    session = FakeSession({
        "https://example.com/job/1": FakeResponse(content=BMS_STYLE_HTML),
        "https://example.com/job/no-ldjson": FakeResponse(content=b"<html>JS shell</html>"),
        # job/missing intentionally has no route -> FakeSession returns 404
    })

    result = enrichment.run(conn, session, "2026-07-16T12:00:00")

    assert result.enriched == 1
    assert result.failed == 2

    def details_for(url):
        job_id = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()["id"]
        return conn.execute("SELECT * FROM job_details WHERE job_id=?", (job_id,)).fetchone()

    ok = details_for("https://example.com/job/1")
    assert ok["enrichment_failed"] == 0
    assert ok["seniority"] == "Senior"

    unreachable = details_for("https://example.com/job/missing")
    assert unreachable["enrichment_failed"] == 1

    no_ldjson = details_for("https://example.com/job/no-ldjson")
    assert no_ldjson["enrichment_failed"] == 1


def test_run_skips_jobs_already_enriched(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://example.com/job/1", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")
    job_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://example.com/job/1",)).fetchone()["id"]
    storage.save_enrichment(conn, job_id, "Already done.", "Senior", [], "2026-07-16T10:30:00")

    session = FakeSession({})  # no routes registered — a call here would fail the test
    result = enrichment.run(conn, session, "2026-07-16T12:00:00")

    assert result.enriched == 0
    assert result.failed == 0
    assert session.calls == []
