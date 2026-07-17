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


def seeded_enriched_conn(tmp_path):
    conn = storage.connect(tmp_path / "e.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://a/1", "p"),
        Job("Abbvie", "QC Analyst", "https://a/2", "p"),
        Job("Abbvie", "Broken Enrichment", "https://a/3", "p"),
    ], "2026-07-17T10:00:00")
    id1 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/1",)).fetchone()["id"]
    id2 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/2",)).fetchone()["id"]
    id3 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/3",)).fetchone()["id"]
    storage.save_enrichment(conn, id1, "Needs SAP and GMP.", "Senior",
                             [("SAP", "Software"), ("GMP", "Regulatory")], "2026-07-17T11:00:00")
    storage.save_enrichment(conn, id2, "QC role, GMP required.", None,
                             [("GMP", "Regulatory")], "2026-07-17T11:00:00")
    storage.save_enrichment(conn, id3, "", None, [], "2026-07-17T11:00:00", failed=True)
    return conn


def test_categorize_titles():
    assert analytics.categorize("QC Analyst II") == "Quality"
    assert analytics.categorize("Process Engineer") == "Engineering"
    assert analytics.categorize("Senior Research Scientist") == "R&D / Science"
    assert analytics.categorize("Regulatory Affairs Manager") == "Regulatory"
    assert analytics.categorize("Something Odd") == "Other"
    # Regression: word-boundary fixes for "it", "hr", "account"
    assert analytics.categorize("Credit Analyst") == "Other"
    assert analytics.categorize("Unit Manager") == "Other"
    assert analytics.categorize("Accountant") == "HR / Finance / Admin"
    assert analytics.categorize("IT Support Engineer") == "Engineering"
    assert analytics.categorize("IT Support Specialist") == "IT / Digital"
    assert analytics.categorize("HR Business Partner") == "HR / Finance / Admin"


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


def test_top_skills_counts_across_jobs(tmp_path):
    conn = seeded_enriched_conn(tmp_path)
    by_skill = {r["skill"]: r["count"] for r in analytics.top_skills(conn)}
    assert by_skill["GMP"] == 2
    assert by_skill["SAP"] == 1


def test_top_skills_respects_limit(tmp_path):
    conn = seeded_enriched_conn(tmp_path)
    rows = analytics.top_skills(conn, limit=1)
    assert len(rows) == 1
    assert rows[0]["skill"] == "GMP"


def test_seniority_breakdown_labels_null_as_unspecified(tmp_path):
    conn = seeded_enriched_conn(tmp_path)
    rows = {r["seniority"]: r["count"] for r in analytics.seniority_breakdown(conn)}
    assert rows["Senior"] == 1
    assert rows["Unspecified"] == 1


def test_seniority_breakdown_excludes_failed_enrichment(tmp_path):
    conn = seeded_enriched_conn(tmp_path)
    total = sum(r["count"] for r in analytics.seniority_breakdown(conn))
    assert total == 2  # the failed-enrichment job (id3) is excluded


def test_skills_by_category(tmp_path):
    conn = seeded_enriched_conn(tmp_path)
    rows = analytics.skills_by_category(conn)
    assert {"category": "Software", "skill": "SAP", "count": 1} in rows
    assert {"category": "Regulatory", "skill": "GMP", "count": 2} in rows
