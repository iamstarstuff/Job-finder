import json

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
