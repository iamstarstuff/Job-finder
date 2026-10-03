from datetime import datetime

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


def seeded_mixed_sector_conn(tmp_path):
    conn = storage.connect(tmp_path / "mixed.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "QC Analyst", "https://a/1", "p"),
    ], "2026-07-01T10:00:00")
    storage.record_company_snapshot(conn, "Google", [
        Job("Google", "Senior SRE", "https://g/1", "p", sector="tech"),
    ], "2026-07-01T10:00:00")
    id1 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/1",)).fetchone()["id"]
    id2 = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://g/1",)).fetchone()["id"]
    storage.save_enrichment(conn, id1, "Needs SAP.", "Senior", [("SAP", "Software")], "2026-07-01T11:00:00")
    storage.save_enrichment(conn, id2, "Needs Kubernetes.", None, [("Kubernetes", "Cloud & Infrastructure")], "2026-07-01T11:00:00")
    return conn


def test_overview_filters_by_sector(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    assert analytics.overview(conn)["total_jobs_seen"] == 2
    assert analytics.overview(conn, sector="pharma")["total_jobs_seen"] == 1
    assert analytics.overview(conn, sector="tech")["total_jobs_seen"] == 1
    assert analytics.overview(conn, sector="tech")["companies"] == 1


def test_top_skills_filters_by_sector(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    pharma_skills = {r["skill"] for r in analytics.top_skills(conn, sector="pharma")}
    tech_skills = {r["skill"] for r in analytics.top_skills(conn, sector="tech")}
    assert pharma_skills == {"SAP"}
    assert tech_skills == {"Kubernetes"}


def test_category_breakdown_filters_by_sector(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    tech_rows = analytics.category_breakdown(conn, sector="tech")
    assert all(r["company"] == "Google" for r in tech_rows)


def test_new_jobs_per_week_filters_by_sector(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    now = datetime(2026, 7, 15)  # keep the July 1 seed inside the default 12-week window
    total_all = sum(r["count"] for r in analytics.new_jobs_per_week(conn, now=now))
    total_pharma = sum(r["count"] for r in analytics.new_jobs_per_week(conn, sector="pharma", now=now))
    assert total_all == 2
    assert total_pharma == 1


def test_median_days_active_filters_by_sector(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    assert analytics.median_days_active(conn, sector="pharma") == []
    assert analytics.median_days_active(conn, sector="tech") == []


def test_sector_none_preserves_existing_unfiltered_behavior(tmp_path):
    conn = seeded_mixed_sector_conn(tmp_path)
    assert analytics.overview(conn)["companies"] == 2


def test_week_start_returns_the_monday():
    assert analytics.week_start("2026-09-15T16:00:00") == "2026-09-14"  # Tuesday
    assert analytics.week_start("2026-09-14T00:00:01") == "2026-09-14"  # Monday stays
    assert analytics.week_start("2026-09-13T23:59:59") == "2026-09-07"  # Sunday


def test_week_label_is_day_and_short_month():
    assert analytics.week_label("2026-09-07") == "7 Sep"
    assert analytics.week_label("2026-12-28") == "28 Dec"


def test_window_cutoff():
    now = datetime(2026, 9, 15, 12, 0, 0)
    assert analytics.window_cutoff(0, now) is None
    assert analytics.window_cutoff(4, now) == "2026-08-18T12:00:00"


def _seed_two_weeks(tmp_path):
    """now is 2026-09-15 12:00 (Tuesday). Timeline:
    09-03 Old first seen (APC)        -> previous week
    09-05 Last week first seen (Amgen) -> previous week
    09-10 Old sighted again           -> last_seen inside the last 7 days
    09-14 New A, New B first seen; Old vanishes -> closed within the last 7 days
    """
    conn = storage.connect(tmp_path / "w.db")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "Old", "https://a/0", "p"),
    ], "2026-09-03T10:00:00")
    storage.record_company_snapshot(conn, "Amgen", [
        Job("Amgen", "Last week", "https://b/1", "p"),
    ], "2026-09-05T10:00:00")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "Old", "https://a/0", "p"),
    ], "2026-09-10T10:00:00")
    storage.record_company_snapshot(conn, "APC", [
        Job("APC", "New A", "https://a/1", "p"),
        Job("APC", "New B", "https://a/2", "p"),
    ], "2026-09-14T10:00:00")
    return conn


def test_overview_reports_week_deltas_and_enrichment(tmp_path):
    conn = _seed_two_weeks(tmp_path)
    now = datetime(2026, 9, 15, 12, 0, 0)
    data = analytics.overview(conn, now=now)
    assert data["new_this_week"] == 2          # New A, New B
    assert data["new_previous_week"] == 2      # Old, Last week
    assert data["closed_last_7d"] == 1         # Old: last seen 09-10, gone on 09-14
    assert data["companies_failing"] == 0
    assert data["enriched_count"] == 0 and data["enriched_pct"] == 0
    job_id = conn.execute("SELECT id FROM jobs WHERE url='https://a/1'").fetchone()["id"]
    storage.save_enrichment(conn, job_id, "GMP work", None, [("GMP", "Regulatory")], "2026-09-14T11:00:00")
    storage.sync_company_failures(conn, "pharma", {"Amgen": "boom"})
    data = analytics.overview(conn, now=now)
    assert data["enriched_count"] == 1 and data["enriched_pct"] == 25  # 1 of 4 jobs
    assert data["companies_failing"] == 1
    assert analytics.overview(conn, sector="tech", now=now)["companies_failing"] == 0


def test_top_skills_respects_window(tmp_path):
    conn = _seed_two_weeks(tmp_path)
    now = datetime(2026, 9, 15, 12, 0, 0)
    old_id = conn.execute("SELECT id FROM jobs WHERE url='https://b/1'").fetchone()["id"]
    new_id = conn.execute("SELECT id FROM jobs WHERE url='https://a/1'").fetchone()["id"]
    storage.save_enrichment(conn, old_id, "SAP", None, [("SAP", "Software")], "2026-09-05T11:00:00")
    storage.save_enrichment(conn, new_id, "GMP", None, [("GMP", "Regulatory")], "2026-09-14T11:00:00")
    assert {r["skill"] for r in analytics.top_skills(conn, now=now)} == {"SAP", "GMP"}
    assert {r["skill"] for r in analytics.top_skills(conn, weeks=1, now=now)} == {"GMP"}


def test_new_jobs_per_week_is_continuous_and_monday_dated(tmp_path):
    conn = _seed_two_weeks(tmp_path)
    now = datetime(2026, 9, 15, 12, 0, 0)
    rows = analytics.new_jobs_per_week(conn, weeks=4, now=now)
    assert [r["week"] for r in rows] == ["2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14"]
    assert [r["count"] for r in rows] == [0, 0, 2, 0, 2]
    assert analytics.new_jobs_per_week(conn, weeks=0, now=now)[0]["week"] == "2026-08-31"


def test_new_jobs_per_week_empty_db_returns_no_rows(tmp_path):
    conn = storage.connect(tmp_path / "empty.db")
    assert analytics.new_jobs_per_week(conn, weeks=0) == []


def _seed_enriched_window(tmp_path):
    """now = 2026-09-15 12:00. Two companies, four enriched jobs across three weeks,
    one failed enrichment, one closed job."""
    conn = storage.connect(tmp_path / "v.db")
    storage.record_company_snapshot(conn, "MSD", [
        Job("MSD", "Senior QC Analyst", "https://m/1", "p"),      # week of 08-24
    ], "2026-08-26T10:00:00")
    storage.record_company_snapshot(conn, "MSD", [
        Job("MSD", "Senior QC Analyst", "https://m/1", "p"),
        Job("MSD", "Director of Quality", "https://m/2", "p"),   # week of 09-07
        Job("MSD", "Broken", "https://m/3", "p"),
    ], "2026-09-09T10:00:00")
    storage.record_company_snapshot(conn, "BMS", [
        Job("BMS", "Process Engineer", "https://b/1", "p"),      # week of 09-07
    ], "2026-09-09T10:00:00")
    storage.record_company_snapshot(conn, "BMS", [
        Job("BMS", "Data Scientist", "https://b/2", "p"),        # week of 09-14; Process Engineer closes (last seen 09-09)
    ], "2026-09-14T10:00:00")
    ids = {u: conn.execute("SELECT id FROM jobs WHERE url=?", (u,)).fetchone()["id"]
           for u in ("https://m/1", "https://m/2", "https://m/3", "https://b/1", "https://b/2")}
    storage.save_enrichment(conn, ids["https://m/1"], "GMP and SAP", "Senior", [("GMP", "Regulatory"), ("SAP", "Software")], "2026-08-26T11:00:00")
    storage.save_enrichment(conn, ids["https://m/2"], "GMP", "Director", [("GMP", "Regulatory")], "2026-09-09T11:00:00")
    storage.save_enrichment(conn, ids["https://m/3"], "", None, [], "2026-09-09T11:00:00", failed=True)
    storage.save_enrichment(conn, ids["https://b/1"], "GMP", None, [("GMP", "Regulatory")], "2026-09-09T11:00:00")
    storage.save_enrichment(conn, ids["https://b/2"], "Python", None, [("Python", "Software")], "2026-09-14T11:00:00")
    return conn


NOW = datetime(2026, 9, 15, 12, 0, 0)


def test_company_velocity_counts_active_and_window_deltas(tmp_path):
    conn = _seed_enriched_window(tmp_path)
    rows = {r["company"]: r for r in analytics.company_velocity(conn, weeks=1, now=NOW)}
    assert rows["MSD"] == {"company": "MSD", "active": 3, "new_in_window": 2, "new_previous_window": 0}
    assert rows["BMS"] == {"company": "BMS", "active": 1, "new_in_window": 2, "new_previous_window": 0}
    all_time = {r["company"]: r for r in analytics.company_velocity(conn, weeks=0, now=NOW)}
    assert all_time["MSD"]["new_in_window"] == 3 and all_time["MSD"]["new_previous_window"] is None
    assert [r["company"] for r in analytics.company_velocity(conn, now=NOW)] == ["MSD", "BMS"]  # active desc


def test_compute_movers_splits_and_ranks():
    rows = [
        {"company": "A", "active": 1, "new_in_window": 5, "new_previous_window": 1},
        {"company": "B", "active": 1, "new_in_window": 0, "new_previous_window": 4},
        {"company": "C", "active": 1, "new_in_window": 2, "new_previous_window": 2},
        {"company": "D", "active": 1, "new_in_window": 9, "new_previous_window": 1},
    ]
    movers = analytics.compute_movers(rows, n=1)
    assert movers == {"up": [{"company": "D", "delta": 8}], "down": [{"company": "B", "delta": -4}],
                      "comparable": True}
    assert analytics.compute_movers([{"company": "A", "active": 1, "new_in_window": 5, "new_previous_window": None}]) == {"up": [], "down": [], "comparable": False}


def test_compute_movers_not_comparable_when_previous_window_is_empty():
    """When the previous window predates the earliest record, every row's
    new_previous_window is 0 and ranking by raw totals would be misleading
    (e.g. crediting a retired company with a huge "rise")."""
    rows = [
        {"company": "A", "active": 1, "new_in_window": 5, "new_previous_window": 0},
        {"company": "B", "active": 1, "new_in_window": 3, "new_previous_window": 0},
    ]
    assert analytics.compute_movers(rows) == {"up": [], "down": [], "comparable": False}


def test_skill_trend_is_dense_and_uses_enriched_totals(tmp_path):
    conn = _seed_enriched_window(tmp_path)
    rows = analytics.skill_trend(conn, weeks=4, limit=3, now=NOW)
    weeks = ["2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14"]
    assert [r["week"] for r in rows][:5] == weeks                       # skill-major, week-minor
    assert [r["skill"] for r in rows][::5] == ["GMP", "Python", "SAP"]  # GMP 3, then the 1-count ties by name
    by = {(r["skill"], r["week"]): (r["count"], r["total"]) for r in rows}
    assert by[("GMP", "2026-09-07")] == (2, 2)   # MSD Director + BMS Process Engineer; "Broken" excluded from total
    assert by[("GMP", "2026-09-14")] == (0, 1)   # Data Scientist is enriched but mentions Python only
    assert by[("SAP", "2026-08-24")] == (1, 1)
    assert analytics.skill_trend(conn, sector="tech", now=NOW) == []


def test_seniority_by_company_labels_null_and_respects_window(tmp_path):
    conn = _seed_enriched_window(tmp_path)
    rows = {(r["company"], r["seniority"]): r["count"] for r in analytics.seniority_by_company(conn, weeks=0, now=NOW)}
    assert rows == {("MSD", "Senior"): 1, ("MSD", "Director"): 1, ("BMS", "Unspecified"): 2}
    recent = {(r["company"], r["seniority"]) for r in analytics.seniority_by_company(conn, weeks=1, now=NOW)}
    assert recent == {("MSD", "Director"), ("BMS", "Unspecified")}


def test_category_breakdown_respects_window(tmp_path):
    conn = _seed_enriched_window(tmp_path)
    all_rows = {(r["company"], r["category"]): r["count"] for r in analytics.category_breakdown(conn, now=NOW)}
    assert all_rows[("MSD", "Quality")] == 2
    recent = {(r["company"], r["category"]): r["count"] for r in analytics.category_breakdown(conn, weeks=1, now=NOW)}
    assert recent[("MSD", "Quality")] == 1


def test_median_days_active_window_and_min_closed(tmp_path):
    conn = _seed_enriched_window(tmp_path)
    rows = analytics.median_days_active(conn, now=NOW)
    assert rows == [{"company": "BMS", "median_days": 0.0, "closed": 1}]  # Process Engineer: seen once, 09-09
    assert analytics.median_days_active(conn, min_closed=3, now=NOW) == []
    assert analytics.median_days_active(conn, weeks=4, now=NOW)[0]["company"] == "BMS"


def test_scraper_health_derives_every_status(tmp_path):
    conn = storage.connect(tmp_path / "h.db")
    for company, sector in (("Pfizer", "pharma"), ("Astellas", "pharma"), ("Leo Pharma", "pharma"),
                            ("Johnson & Johnson", "pharma"), ("Google", "tech")):
        storage.record_company_snapshot(conn, company, [
            Job(company, "Role", f"https://{company}/1", "p", sector=sector),
        ], "2026-09-14T10:00:00")
    storage.sync_company_failures(conn, "pharma", {
        "Astellas": "404 Client Error: Not Found",
        "Leo Pharma": "returned 0 jobs but previously had active listings",
    })
    registries = {"pharma": ["Pfizer", "Astellas", "Leo Pharma", "Stripe-new"], "tech": ["Google"]}
    rows = analytics.scraper_health(conn, registries)
    status = {r["company"]: r["status"] for r in rows}
    assert status == {"Astellas": "failing", "Leo Pharma": "empty", "Johnson & Johnson": "retired",
                      "Pfizer": "ok", "Google": "ok", "Stripe-new": "ok"}
    assert [r["company"] for r in rows][:3] == ["Astellas", "Leo Pharma", "Johnson & Johnson"]  # problems first
    pfizer = next(r for r in rows if r["company"] == "Pfizer")
    assert pfizer == {"sector": "pharma", "company": "Pfizer", "status": "ok", "active": 1,
                      "last_seen": "2026-09-14T10:00:00", "error": None}
    stripe = next(r for r in rows if r["company"] == "Stripe-new")
    assert stripe["active"] == 0 and stripe["last_seen"] is None


def test_run_history_computes_duration_and_failed_names(tmp_path):
    conn = storage.connect(tmp_path / "r.db")
    run_id = storage.start_run(conn, "2026-09-15T16:00:00", "pharma")
    storage.finish_run(conn, run_id, "2026-09-15T16:00:21", 355, 0, {"Astellas": "404", "Leo": "zero"})
    storage.start_run(conn, "2026-09-15T17:00:00", "pharma")  # still running
    storage.start_run(conn, "2026-09-15T08:00:00", "tech")
    rows = analytics.run_history(conn, "pharma")
    assert rows[0] == {"started_at": "2026-09-15T17:00:00", "duration_s": None, "total_jobs": None,
                       "new_jobs": None, "failed": []}
    assert rows[1] == {"started_at": "2026-09-15T16:00:00", "duration_s": 21, "total_jobs": 355,
                       "new_jobs": 0, "failed": ["Astellas", "Leo"]}
    assert len(analytics.run_history(conn, "tech")) == 1
    assert len(analytics.run_history(conn, "pharma", limit=1)) == 1


def test_scraper_health_reports_failures_for_registry_only_companies(tmp_path):
    """Registry companies with no job rows but failure entries should show failing/empty status."""
    conn = storage.connect(tmp_path / "h2.db")
    # Create one company with jobs
    storage.record_company_snapshot(conn, "Pfizer", [
        Job("Pfizer", "Role", "https://pfizer/1", "p", sector="pharma"),
    ], "2026-09-14T10:00:00")

    # Add failures for registry-only companies (no job rows)
    storage.sync_company_failures(conn, "pharma", {
        "NewCo": "ConnectionError: could not reach site",
        "AnotherNew": "returned 0 jobs but previously had active listings",
    })

    registries = {"pharma": ["Pfizer", "NewCo", "AnotherNew"]}
    rows = analytics.scraper_health(conn, registries)
    status = {r["company"]: r["status"] for r in rows}

    # NewCo should be "failing" (has error message that doesn't start with "returned 0 jobs")
    # AnotherNew should be "empty" (has "returned 0 jobs" message)
    assert status == {"NewCo": "failing", "AnotherNew": "empty", "Pfizer": "ok"}

    new_co = next(r for r in rows if r["company"] == "NewCo")
    assert new_co["error"] == "ConnectionError: could not reach site"
    assert new_co["active"] == 0
    assert new_co["last_seen"] is None

    another = next(r for r in rows if r["company"] == "AnotherNew")
    assert another["error"] == "returned 0 jobs but previously had active listings"
    assert another["status"] == "empty"


def test_removed_analytics_functions_are_gone():
    for name in ("jobs_per_company", "seniority_breakdown", "skills_by_category"):
        assert not hasattr(analytics, name), name
