from jobfinder import config, emailer, storage
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


def test_error_html_includes_recovered_section():
    html = emailer.render_error_html({}, [], ["Johnson & Johnson"])
    assert "Johnson &amp; Johnson" in html
    assert "Recovered" in html


def test_error_html_omits_recovered_section_when_none():
    html = emailer.render_error_html({"Amgen": "HTTP 500"}, [])
    assert "Recovered" not in html


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


def test_send_run_notifications_skips_error_email_on_repeat_failure(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))

    result = RunResult(run_id=1, failures={"Johnson & Johnson": "403 Client Error: Forbidden"})
    emailer.send_run_notifications(conn, result)
    emailer.send_run_notifications(conn, result)
    emailer.send_run_notifications(conn, result)

    error_emails = [s for s in sent if s == "Job Scraper Error Notification"]
    assert len(error_emails) == 1  # only the first failure sent an email


def test_send_run_notifications_sends_email_on_recovery(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append((subject, html)))

    emailer.send_run_notifications(
        conn, RunResult(run_id=1, failures={"Johnson & Johnson": "403 error"}),
    )
    emailer.send_run_notifications(conn, RunResult(run_id=2))  # no failures this run -> recovered

    error_emails = [h for s, h in sent if s == "Job Scraper Error Notification"]
    assert len(error_emails) == 2  # one for the failure, one for the recovery
    assert "Johnson &amp; Johnson" in error_emails[1]
    assert "Recovered" in error_emails[1]


def test_send_run_notifications_no_error_email_when_nothing_ever_failed(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))
    emailer.send_run_notifications(conn, RunResult(run_id=1))
    assert "Job Scraper Error Notification" not in sent


def test_send_tech_digest_skips_error_email_on_repeat_failure(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))

    result = RunResult(run_id=1, failures={"Google": "timeout"})
    emailer.send_tech_digest(conn, result)
    emailer.send_tech_digest(conn, result)

    error_emails = [s for s in sent if s == "Tech Job Scraper Error Notification"]
    assert len(error_emails) == 1


def test_send_run_notifications_and_tech_digest_track_failures_independently(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))

    # Same company name failing in both sectors should be tracked separately.
    emailer.send_run_notifications(conn, RunResult(run_id=1, failures={"Amgen": "boom"}))
    emailer.send_tech_digest(conn, RunResult(run_id=2, failures={"Amgen": "boom"}))

    assert sent.count("Job Scraper Error Notification") == 1
    assert sent.count("Tech Job Scraper Error Notification") == 1


def test_send_tech_digest_uses_tech_recipients_and_kind(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    sent = {}

    def fake_send_email(subject, html, recipients):
        sent["subject"] = subject
        sent["recipients"] = recipients

    monkeypatch.setattr(emailer, "send_email", fake_send_email)

    tech_jobs = {"Google": [Job("Google", "Senior SRE", "https://g/1", "https://g", sector="tech")]}
    result = RunResult(run_id=1, new_jobs=tech_jobs)
    emailer.send_tech_digest(conn, result)

    assert sent["recipients"] == config.TECH_ALERT_RECIPIENTS
    row = conn.execute("SELECT kind FROM emails ORDER BY id DESC LIMIT 1").fetchone()
    assert row["kind"] == "tech_alert"


def test_dry_run_send_email_never_opens_smtp(monkeypatch):
    monkeypatch.setenv("JOBFINDER_DRY_RUN", "1")
    def no_smtp(*args, **kwargs):
        raise AssertionError("SMTP must not be used in a dry run")
    monkeypatch.setattr(emailer.smtplib, "SMTP_SSL", no_smtp)
    emailer.send_email("Subject", "<p>hi</p>", ["someone@example.com"])


def test_dry_run_notifications_are_not_sent_or_recorded(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setenv("JOBFINDER_DRY_RUN", "1")
    sent = []
    monkeypatch.setattr(emailer, "send_email", lambda subject, html, recipients: sent.append(subject))
    emailer.send_run_notifications(conn, RunResult(run_id=1, new_jobs=NEW, failures={"Amgen": "boom"}))
    assert sent == []
    assert conn.execute("SELECT COUNT(*) c FROM emails").fetchone()["c"] == 0
