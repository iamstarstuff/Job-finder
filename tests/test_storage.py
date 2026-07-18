import json
import sqlite3

from jobfinder import storage
from jobfinder.models import Job


def make_conn(tmp_path):
    return storage.connect(tmp_path / "test.db")


JOB_A = Job("APC", "QC Analyst", "https://approcess.com/jobs/1", "https://approcess.com/careers")
JOB_B = Job("APC", "Process Engineer", "https://approcess.com/jobs/2", "https://approcess.com/careers")


def test_first_snapshot_all_jobs_are_new(tmp_path):
    conn = make_conn(tmp_path)
    new = storage.record_company_snapshot(conn, "APC", [JOB_A, JOB_B], "2026-07-05T10:00:00")
    assert {j.title for j in new} == {"QC Analyst", "Process Engineer"}


def test_second_snapshot_detects_only_new_and_updates_last_seen(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "APC", [JOB_A], "2026-07-05T10:00:00")
    new = storage.record_company_snapshot(conn, "APC", [JOB_A, JOB_B], "2026-07-05T11:00:00")
    assert [j.title for j in new] == ["Process Engineer"]
    row = conn.execute("SELECT first_seen, last_seen FROM jobs WHERE url=?", (JOB_A.url,)).fetchone()
    assert row["first_seen"] == "2026-07-05T10:00:00"
    assert row["last_seen"] == "2026-07-05T11:00:00"


def test_vanished_jobs_deactivated_and_reposted_job_is_not_new(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "APC", [JOB_A, JOB_B], "2026-07-05T10:00:00")
    storage.record_company_snapshot(conn, "APC", [JOB_A], "2026-07-05T11:00:00")
    row = conn.execute("SELECT is_active FROM jobs WHERE url=?", (JOB_B.url,)).fetchone()
    assert row["is_active"] == 0
    # reappears -> reactivated but NOT reported as new (dedup by URL)
    new = storage.record_company_snapshot(conn, "APC", [JOB_A, JOB_B], "2026-07-05T12:00:00")
    assert new == []
    row = conn.execute("SELECT is_active FROM jobs WHERE url=?", (JOB_B.url,)).fetchone()
    assert row["is_active"] == 1


def test_run_and_email_logging(tmp_path):
    conn = make_conn(tmp_path)
    run_id = storage.start_run(conn, "2026-07-05T10:00:00")
    storage.finish_run(conn, run_id, "2026-07-05T10:01:00", 12, 2, {"Amgen": "HTTP 500"})
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    assert row["new_jobs"] == 2
    assert json.loads(row["failed_companies"]) == {"Amgen": "HTTP 500"}
    storage.log_email(conn, "2026-07-05T10:01:05", "alert", "New Jobs", ["a@b.com"], True)
    assert conn.execute("SELECT COUNT(*) c FROM emails").fetchone()["c"] == 1


def test_migrate_legacy_json(tmp_path):
    legacy = tmp_path / "jobs.json"
    legacy.write_text(json.dumps({
        "Abbvie": [{"company": "Abbvie", "title": "Warehouse Supervisor",
                    "application link": "https://careers.abbvie.com/en/job/x",
                    "job portal link": "https://careers.abbvie.com/en/jobs"}],
        "Takeda": [{"company": "Takeda", "title": "QA Lead",
                    "application url": "https://jobs.takeda.com/job/y",
                    "job portal link": "https://jobs.takeda.com/search"}],
    }))
    conn = make_conn(tmp_path)
    count = storage.migrate_legacy_json(conn, legacy, "2026-07-05T10:00:00")
    assert count == 2
    # both old field spellings map to url
    urls = {r["url"] for r in conn.execute("SELECT url FROM jobs")}
    assert urls == {"https://careers.abbvie.com/en/job/x", "https://jobs.takeda.com/job/y"}


def test_find_unenriched_jobs_returns_only_jobs_without_details(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://a/1", "https://a/careers"),
        Job("Abbvie", "QA Specialist", "https://a/2", "https://a/careers"),
    ], "2026-07-16T10:00:00")
    job1_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://a/1",)).fetchone()["id"]
    storage.save_enrichment(conn, job1_id, "Some description", "Senior", [], "2026-07-16T11:00:00")
    unenriched = storage.find_unenriched_jobs(conn)
    assert [r["url"] for r in unenriched] == ["https://a/2"]


def test_find_unenriched_jobs_filters_by_companies(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://a/1", "https://a/careers"),
    ], "2026-07-16T10:00:00")
    storage.record_company_snapshot(conn, "Astellas", [
        Job("Astellas", "QC Analyst", "https://b/1", "https://b/careers"),
    ], "2026-07-16T10:00:00")

    filtered = storage.find_unenriched_jobs(conn, companies=["Abbvie", "BMS"])
    assert [r["url"] for r in filtered] == ["https://a/1"]

    unfiltered = storage.find_unenriched_jobs(conn)
    assert {r["url"] for r in unfiltered} == {"https://a/1", "https://b/1"}


def test_save_enrichment_writes_details_and_skills(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "Abbvie", [JOB_A], "2026-07-16T10:00:00")
    job_id = conn.execute("SELECT id FROM jobs WHERE url=?", (JOB_A.url,)).fetchone()["id"]
    storage.save_enrichment(
        conn, job_id, "Needs SAP and GMP.", "Senior",
        [("SAP", "Software"), ("GMP", "Regulatory")], "2026-07-16T11:00:00",
    )
    details = conn.execute("SELECT * FROM job_details WHERE job_id=?", (job_id,)).fetchone()
    assert details["description"] == "Needs SAP and GMP."
    assert details["seniority"] == "Senior"
    assert details["enrichment_failed"] == 0
    skill_names = {
        r["name"] for r in conn.execute(
            """SELECT skills.name FROM job_skills
               JOIN skills ON skills.id = job_skills.skill_id
               WHERE job_skills.job_id = ?""", (job_id,)
        ).fetchall()
    }
    assert skill_names == {"SAP", "GMP"}


def test_save_enrichment_failed_writes_no_skills(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "Abbvie", [JOB_A], "2026-07-16T10:00:00")
    job_id = conn.execute("SELECT id FROM jobs WHERE url=?", (JOB_A.url,)).fetchone()["id"]
    storage.save_enrichment(conn, job_id, "", None, [], "2026-07-16T11:00:00", failed=True)
    details = conn.execute("SELECT * FROM job_details WHERE job_id=?", (job_id,)).fetchone()
    assert details["enrichment_failed"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM job_skills WHERE job_id=?", (job_id,)).fetchone()["c"] == 0


def test_save_enrichment_reuses_existing_skill_row(tmp_path):
    conn = make_conn(tmp_path)
    storage.record_company_snapshot(conn, "Abbvie", [JOB_A, JOB_B], "2026-07-16T10:00:00")
    id_a = conn.execute("SELECT id FROM jobs WHERE url=?", (JOB_A.url,)).fetchone()["id"]
    id_b = conn.execute("SELECT id FROM jobs WHERE url=?", (JOB_B.url,)).fetchone()["id"]
    storage.save_enrichment(conn, id_a, "Needs SAP.", None, [("SAP", "Software")], "2026-07-16T11:00:00")
    storage.save_enrichment(conn, id_b, "Also needs SAP.", None, [("SAP", "Software")], "2026-07-16T11:01:00")
    assert conn.execute("SELECT COUNT(*) c FROM skills WHERE name='SAP'").fetchone()["c"] == 1


def test_connect_migrates_sector_column_on_existing_db(tmp_path):
    db_path = tmp_path / "old.db"
    # Simulate a pre-existing DB created before the sector column existed.
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE jobs (
        id INTEGER PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL,
        url TEXT, portal_url TEXT, closing_date TEXT, job_key TEXT NOT NULL UNIQUE,
        first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1)""")
    conn.execute(
        """INSERT INTO jobs (company, title, url, portal_url, job_key, first_seen, last_seen)
           VALUES ('Abbvie', 'QC Analyst', 'https://a/1', 'https://a', 'k1', 'now', 'now')"""
    )
    conn.commit()
    conn.close()

    conn = storage.connect(db_path)
    row = conn.execute("SELECT sector FROM jobs WHERE company = 'Abbvie'").fetchone()
    assert row["sector"] == "pharma"


def test_connect_on_fresh_db_has_sector_column(tmp_path):
    conn = storage.connect(tmp_path / "fresh.db")
    columns = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)")]
    assert "sector" in columns


def test_record_company_snapshot_defaults_sector_to_pharma(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "QC Analyst", "https://a/1", "https://a"),
    ], "2026-07-18T10:00:00")
    row = conn.execute("SELECT sector FROM jobs WHERE company = 'Abbvie'").fetchone()
    assert row["sector"] == "pharma"


def test_record_company_snapshot_stores_explicit_tech_sector(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Google", [
        Job("Google", "Senior SRE", "https://g/1", "https://g", sector="tech"),
    ], "2026-07-18T10:00:00")
    row = conn.execute("SELECT sector FROM jobs WHERE company = 'Google'").fetchone()
    assert row["sector"] == "tech"
