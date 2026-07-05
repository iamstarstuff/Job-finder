from jobfinder import emailer, storage
from jobfinder.models import Job
from jobfinder.runner import RunResult

NEW = {"APC": [Job("APC", "QC Analyst", "https://approcess.com/jobs/1",
                   "https://approcess.com/careers", "2026-08-01")]}


def test_alert_html_contains_job_link_and_title():
    html = emailer.render_new_jobs_html(NEW)
    assert "QC Analyst" in html
    assert 'href="https://approcess.com/jobs/1"' in html
    assert "APC" in html
    assert "2026-08-01" in html  # closing date shown when present


def test_alert_html_escapes_content():
    jobs = {"X": [Job("X", "<script>alert(1)</script>", "https://x.example/1", "https://x.example")]}
    html = emailer.render_new_jobs_html(jobs)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_error_html_lists_failures_and_warnings():
    html = emailer.render_error_html({"Amgen": "HTTP 500"}, ["Takeda"])
    assert "Amgen" in html and "HTTP 500" in html
    assert "Takeda" in html and "0 jobs" in html


def test_send_run_notifications_logs_emails(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))
    result = RunResult(run_id=1, new_jobs=NEW, failures={"Amgen": "boom"})
    emailer.send_run_notifications(conn, result)
    assert len(sent) == 2  # one alert, one error email
    rows = conn.execute("SELECT kind, success FROM emails ORDER BY id").fetchall()
    assert [r["kind"] for r in rows] == ["alert", "error"]
    assert all(r["success"] == 1 for r in rows)


def test_send_failure_is_logged_not_raised(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    def boom(subject, html, recipients):
        raise RuntimeError("smtp down")
    monkeypatch.setattr(emailer, "send_email", boom)
    emailer.send_run_notifications(conn, RunResult(run_id=1, new_jobs=NEW))
    row = conn.execute("SELECT success, error FROM emails").fetchone()
    assert row["success"] == 0
    assert "smtp down" in row["error"]
