from jobfinder import analytics, storage
from jobfinder.models import Job


def seeded_conn(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "QC Analyst II", "https://a/1", "p"),
        Job("APC", "Process Engineer", "https://a/2", "p"),
    ], "2026-07-01T10:00:00")
    storage.record_company_snapshot(conn, "Amgen", [
        Job("Amgen", "Senior Quality Specialist", "https://b/1", "p"),
    ], "2026-07-03T10:00:00")
    # QC Analyst II vanishes -> completed lifespan of 4 days
    # Corrected seeding from brief: snapshot on July 5 at 10:00 still containing QC Analyst II
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "QC Analyst II", "https://a/1", "p"),
        Job("APC", "Process Engineer", "https://a/2", "p"),
    ], "2026-07-05T10:00:00")
    # Then at 11:00 without it -> lifespan 2026-07-01..2026-07-05 = 4.0 days
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "Process Engineer", "https://a/2", "p"),
    ], "2026-07-05T11:00:00")
    return conn


def test_categorize_titles():
    assert analytics.categorize("QC Analyst II") == "Quality"
    assert analytics.categorize("Process Engineer") == "Engineering"
    assert analytics.categorize("Senior Research Scientist") == "R&D / Science"
    assert analytics.categorize("Regulatory Affairs Manager") == "Regulatory"
    assert analytics.categorize("Something Odd") == "Other"


def test_jobs_per_company(tmp_path):
    conn = seeded_conn(tmp_path)
    rows = {r["company"]: r for r in analytics.jobs_per_company(conn)}
    assert rows["APC"]["total"] == 2
    assert rows["APC"]["active"] == 1
    assert rows["Amgen"]["active"] == 1


def test_category_breakdown(tmp_path):
    conn = seeded_conn(tmp_path)
    rows = analytics.category_breakdown(conn)
    assert {"company": "APC", "category": "Quality", "count": 1} in rows
    assert {"company": "APC", "category": "Engineering", "count": 1} in rows


def test_median_days_active(tmp_path):
    conn = seeded_conn(tmp_path)
    rows = {r["company"]: r["median_days"] for r in analytics.median_days_active(conn)}
    assert rows["APC"] == 4.0


def test_overview_smoke(tmp_path):
    conn = seeded_conn(tmp_path)
    data = analytics.overview(conn)
    assert data["total_jobs_seen"] == 3
    assert data["active_jobs"] == 2
    assert data["companies"] == 2
