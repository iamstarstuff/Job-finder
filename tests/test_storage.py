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
