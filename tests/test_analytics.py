from collections import Counter
from datetime import datetime

from jobfinder import analytics, storage
from jobfinder.models import Job
from tests.conftest import save_reading


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
    for name in ("jobs_per_company", "seniority_breakdown", "skills_by_category", "top_skills",
                 "skill_trend", "seniority_by_company", "category_breakdown", "categorize",
                 "CATEGORY_KEYWORDS"):
        assert not hasattr(analytics, name), name


def _records_conn(tmp_path):
    conn = storage.connect(tmp_path / "records.db")
    read = Job("Google", "Data Scientist", "https://g/1", "p", sector="tech")
    refused = Job("Google", "Sales Lead", "https://g/2", "p", sector="tech")
    unread = Job("APC", "Warehouse Lead", "https://a/1", "p")
    storage.record_company_snapshot(conn, "Google", [read, refused], "2026-09-01T10:00:00")
    storage.record_company_snapshot(conn, "APC", [unread], "2026-10-08T10:00:00")
    gid = conn.execute("SELECT id FROM jobs WHERE url='https://g/1'").fetchone()["id"]
    storage.save_enrichment(conn, gid, "Builds models in Python.", None, [], "2026-09-01T11:00:00")
    save_reading(conn, read, role_family="Data Science", seniority="Mid", min_years_experience=3,
                 skills=["Python", "SQL"], required_languages=["German"], salary_min=90000.0,
                 salary_max=92000.0, salary_currency="EUR", salary_period="year",
                 work_mode="hybrid", contract_type="permanent", reason="Data science role.")
    save_reading(conn, refused, status="refused")
    return conn


def test_job_records_join_jobs_descriptions_and_ok_readings(tmp_path):
    records = {r.title: r for r in analytics.job_records(_records_conn(tmp_path))}
    ds = records["Data Scientist"]
    assert ds.read_by_claude and ds.description == "Builds models in Python."
    assert ds.skills == ("Python", "SQL") and ds.languages == ("German",)
    assert (ds.role_family, ds.seniority, ds.min_years) == ("Data Science", "Mid", 3)
    assert (ds.work_mode, ds.contract_type, ds.reason) == ("hybrid", "permanent", "Data science role.")
    assert (ds.salary_min, ds.salary_max, ds.salary_currency, ds.salary_period) == (90000.0, 92000.0, "EUR", "year")
    assert ds.is_active and ds.sector == "tech" and ds.url == "https://g/1"
    refused = records["Sales Lead"]
    assert not refused.read_by_claude and refused.skills == () and refused.role_family is None
    unread = records["Warehouse Lead"]
    assert not unread.read_by_claude and unread.description is None


def test_job_records_are_newest_first_and_scoped_by_sector_and_window(tmp_path):
    conn = _records_conn(tmp_path)
    assert [r.title for r in analytics.job_records(conn)][0] == "Warehouse Lead"
    assert {r.title for r in analytics.job_records(conn, sector="tech")} == {"Data Scientist", "Sales Lead"}
    now = datetime(2026, 10, 10, 12, 0, 0)
    assert [r.title for r in analytics.job_records(conn, weeks=1, now=now)] == ["Warehouse Lead"]
    assert [r.title for r in analytics._read_records(conn, None, 0, now)] == ["Data Scientist"]


def test_skill_key_folds_case_and_surrounding_space():
    assert analytics.skill_key("  Distributed Systems ") == analytics.skill_key("distributed systems")


def test_merge_skill_names_keeps_the_most_common_spelling():
    names = analytics.merge_skill_names(Counter({
        "Distributed systems": 18, "Distributed Systems": 19, "SQL": 21, "sql": 2, "Gmp": 1, "GMP": 1,
    }))
    assert names == {"distributed systems": "Distributed Systems", "sql": "SQL", "gmp": "GMP"}


READ_NOW = datetime(2026, 10, 10, 12, 0, 0)


def _readings_conn(tmp_path):
    """Tech: Data Scientist (10-07, DS/Mid, Python+SQL), ML Engineer (09-28,
    ML/AI/Senior, python+PyTorch), SDE RDS (AWS 10-07, Cloud/Platform, Python+AWS),
    a refused AWS Sales Specialist. Pharma: QC Analyst (Pfizer 10-08, Quality/
    Junior, GMP) and an unread Warehouse Lead (APC 10-08)."""
    conn = storage.connect(tmp_path / "readings.db")
    ds = Job("Google", "Data Scientist", "https://g/1", "p", sector="tech")
    ml = Job("Google", "ML Engineer", "https://g/2", "p", sector="tech")
    sde = Job("AWS", "SDE, RDS", "https://a/1", "p", sector="tech")
    sales = Job("AWS", "Sales Specialist", "https://a/2", "p", sector="tech")
    qc = Job("Pfizer", "QC Analyst", "https://p/1", "p")
    wh = Job("APC", "Warehouse Lead", "https://x/1", "p")
    storage.record_company_snapshot(conn, "Google", [ml], "2026-09-28T10:00:00")
    storage.record_company_snapshot(conn, "Google", [ml, ds], "2026-10-07T10:00:00")
    storage.record_company_snapshot(conn, "AWS", [sde, sales], "2026-10-07T10:00:00")
    storage.record_company_snapshot(conn, "Pfizer", [qc], "2026-10-08T10:00:00")
    storage.record_company_snapshot(conn, "APC", [wh], "2026-10-08T10:00:00")
    save_reading(conn, ds, role_family="Data Science", seniority="Mid", skills=["Python", "SQL"])
    save_reading(conn, ml, role_family="ML/AI", seniority="Senior", skills=["python", "PyTorch"])
    save_reading(conn, sde, role_family="Cloud/Platform", skills=["Python", "AWS"])
    save_reading(conn, sales, status="refused")
    save_reading(conn, qc, role_family="Quality", seniority="Junior", skills=["GMP"])
    return conn


def test_skill_demand_merges_spellings_and_counts_roles(tmp_path):
    conn = _readings_conn(tmp_path)
    assert analytics.skill_demand(conn, sector="tech", now=READ_NOW) == [
        {"skill": "Python", "count": 3}, {"skill": "AWS", "count": 1},
        {"skill": "PyTorch", "count": 1}, {"skill": "SQL", "count": 1}]
    assert [r["skill"] for r in analytics.skill_demand(conn, limit=2, now=READ_NOW)] == ["Python", "AWS"]
    recent = {r["skill"]: r["count"] for r in analytics.skill_demand(conn, weeks=1, now=READ_NOW)}
    assert recent == {"Python": 2, "AWS": 1, "SQL": 1, "GMP": 1}  # the ML Engineer is older than a week


def test_skill_shares_by_week_is_dense_over_roles_read(tmp_path):
    rows = analytics.skill_shares_by_week(_readings_conn(tmp_path), sector="tech", weeks=4, limit=2, now=READ_NOW)
    weeks = ["2026-09-07", "2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]
    assert [r["week"] for r in rows] == weeks * 2 and [r["skill"] for r in rows][::5] == ["Python", "AWS"]
    by = {(r["skill"], r["week"]): (r["count"], r["total"]) for r in rows}
    assert by[("Python", "2026-09-28")] == (1, 1)
    assert by[("Python", "2026-10-05")] == (2, 2)
    assert by[("AWS", "2026-10-05")] == (1, 2)
    assert by[("AWS", "2026-09-07")] == (0, 0)
    assert analytics.skill_shares_by_week(_readings_conn(tmp_path), sector="tech", weeks=4, now=datetime(2027, 6, 1)) == []


def test_seniority_and_family_counts_use_claude_fields(tmp_path):
    conn = _readings_conn(tmp_path)
    seniority = {(r["company"], r["seniority"]): r["count"]
                 for r in analytics.seniority_counts(conn, sector="tech", weeks=0, now=READ_NOW)}
    assert seniority == {("AWS", "Not stated"): 1, ("Google", "Mid"): 1, ("Google", "Senior"): 1}
    families = {(r["company"], r["family"]): r["count"] for r in analytics.family_counts(conn, now=READ_NOW)}
    assert families == {("AWS", "Cloud/Platform"): 1, ("Google", "Data Science"): 1,
                        ("Google", "ML/AI"): 1, ("Pfizer", "Quality"): 1}


def test_claude_drilldown_lists_the_roles_behind_each_value(tmp_path):
    conn = _readings_conn(tmp_path)

    def titles(dimension, value, **kw):
        return {r["title"] for r in analytics.claude_drilldown(conn, dimension, value, now=READ_NOW, **kw)}

    assert titles("skill", "PYTHON", sector="tech") == {"Data Scientist", "ML Engineer", "SDE, RDS"}
    assert titles("skill", "python", families=("ML/AI",)) == {"ML Engineer"}
    assert titles("skill", "python", levels=("Mid",)) == {"Data Scientist"}
    assert titles("skill", "python", weeks=1) == {"Data Scientist", "SDE, RDS"}
    assert titles("seniority", "Not stated") == {"SDE, RDS"}
    assert titles("role_family", "Quality") == {"QC Analyst"}
    assert titles("company_family", "Google::ML/AI") == {"ML Engineer"}
    row = analytics.claude_drilldown(conn, "role_family", "Quality", now=READ_NOW)[0]
    assert set(row) == {"title", "company", "url", "first_seen"}
    assert analytics.claude_drilldown(conn, "category", "Quality", now=READ_NOW) is None


LEARN_NOW = datetime(2026, 9, 15, 12, 0, 0)


def _roles_conn(tmp_path):
    """Six Google tech roles first seen 09-10: five ML/AI (three Senior, two
    Mid) and one Cloud/Platform (Mid). Python in all, PyTorch in the first two.
    Years: 3, 5, 7, unstated, 4 (ML/AI) and 6 (Cloud/Platform)."""
    conn = storage.connect(tmp_path / "roles.db")
    jobs = [Job("Google", f"Role {i}", f"https://g/{i}", "p", sector="tech") for i in range(6)]
    storage.record_company_snapshot(conn, "Google", jobs, "2026-09-10T10:00:00")
    for i, job in enumerate(jobs):
        save_reading(conn, job, role_family="ML/AI" if i < 5 else "Cloud/Platform",
                     seniority="Senior" if i < 3 else "Mid",
                     skills=["Python", "PyTorch"] if i < 2 else ["Python"],
                     min_years_experience=[3, 5, 7, None, 4, 6][i])
    return conn


def test_skills_for_roles_counts_x_of_n_within_the_chosen_roles(tmp_path):
    conn = _roles_conn(tmp_path)
    assert analytics.skills_for_roles(conn, now=LEARN_NOW) == {
        "roles": 6, "skills": [{"skill": "Python", "count": 6}, {"skill": "PyTorch", "count": 2}]}
    ml = analytics.skills_for_roles(conn, families=("ML/AI",), now=LEARN_NOW)
    assert ml["roles"] == 5
    senior = analytics.skills_for_roles(conn, families=("ML/AI",), levels=("Senior",), now=LEARN_NOW)
    assert senior["roles"] == 3 and senior["skills"][0] == {"skill": "Python", "count": 3}
    assert analytics.MIN_ROLES_FOR_SKILLS == 5


def test_experience_by_family_takes_the_median_of_stated_years(tmp_path):
    rows = analytics.experience_by_family(_roles_conn(tmp_path), now=LEARN_NOW)
    assert rows == [
        {"family": "ML/AI", "median": 4.5, "stated": 4, "total": 5},
        {"family": "Cloud/Platform", "median": None, "stated": 1, "total": 1},  # fewer than 3 stated
    ]


def test_openings_by_family_is_dense_for_the_largest_families(tmp_path):
    rows = analytics.openings_by_family(_roles_conn(tmp_path), weeks=4, now=LEARN_NOW)
    weeks = ["2026-08-17", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-14"]
    assert [r["week"] for r in rows] == weeks * 2
    assert [r["family"] for r in rows][::5] == ["ML/AI", "Cloud/Platform"]
    assert [r["count"] for r in rows] == [0, 0, 0, 5, 0, 0, 0, 0, 1, 0]
    assert analytics.openings_by_family(_roles_conn(tmp_path), weeks=4, top=1, now=LEARN_NOW)[0]["family"] == "ML/AI"
    assert len(analytics.openings_by_family(_roles_conn(tmp_path), weeks=4, top=1, now=LEARN_NOW)) == 5


def test_families_in_lists_role_families_largest_first(tmp_path):
    conn = _roles_conn(tmp_path)
    assert analytics.families_in(conn, "tech") == ["ML/AI", "Cloud/Platform"]
    assert analytics.families_in(conn, "pharma") == []
