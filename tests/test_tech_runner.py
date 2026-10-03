from datetime import datetime

from jobfinder import storage, tech_runner
from jobfinder.models import Job


def good_scraper(session):
    return [Job("Good Tech Co", "Senior SRE", "https://good.example/1", "https://good.example", sector="tech")]


def bad_scraper(session):
    raise RuntimeError("layout changed")


def empty_scraper(session):
    return []


def test_failures_are_captured_not_swallowed(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": good_scraper, "Bad Co": bad_scraper})
    result = tech_runner.run_scrape(conn, session=None, now="2026-07-18T10:00:00")
    assert "Bad Co" in result.failures
    assert "layout changed" in result.failures["Bad Co"]
    assert result.new_jobs == {"Good Tech Co": [good_scraper(None)[0]]}


def test_zero_jobs_after_having_jobs_raises_warning(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": good_scraper})
    tech_runner.run_scrape(conn, session=None, now="2026-07-18T10:00:00")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": empty_scraper})
    result = tech_runner.run_scrape(conn, session=None, now="2026-07-18T11:00:00")
    assert result.zero_warnings == ["Good Tech Co"]


def test_new_jobs_are_stored_with_tech_sector(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": good_scraper})
    tech_runner.run_scrape(conn, session=None, now="2026-07-18T10:00:00")
    row = conn.execute("SELECT sector FROM jobs WHERE company = 'Good Tech Co'").fetchone()
    assert row["sector"] == "tech"


def non_matching_scraper(session):
    # A live listing that has jobs, none of which are target roles (AIB on
    # 2026-09-15: 9 Ireland postings, all retail/compliance).
    return [Job("Good Tech Co", "Branch Customer Advisor", "https://good.example/2", "https://good.example", sector="tech")]


def test_runner_applies_role_filter_and_closes_vanished_jobs_when_listing_is_nonempty(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": good_scraper})
    tech_runner.run_scrape(conn, session=None, now="2026-07-18T10:00:00")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": non_matching_scraper})
    result = tech_runner.run_scrape(conn, session=None, now="2026-07-19T10:00:00")
    assert result.zero_warnings == []          # the listing was not empty, so no layout-change alarm
    assert result.new_jobs == {}               # non-target roles are never stored
    assert conn.execute("SELECT COUNT(*) c FROM jobs WHERE title='Branch Customer Advisor'").fetchone()["c"] == 0
    assert conn.execute("SELECT is_active FROM jobs WHERE title='Senior SRE'").fetchone()["is_active"] == 0


def test_zero_jobs_is_accepted_after_grace_period(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": good_scraper})
    tech_runner.run_scrape(conn, session=None, now="2026-07-18T10:00:00")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": empty_scraper})
    result = tech_runner.run_scrape(conn, session=None, now="2026-07-26T10:00:00")  # 8 days of silence
    assert result.zero_warnings == []
    assert conn.execute("SELECT is_active FROM jobs WHERE company='Good Tech Co'").fetchone()["is_active"] == 0


def test_tech_run_is_not_due_before_the_daily_hour(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    assert tech_runner.is_due(conn, datetime(2026, 10, 3, 7, 20)) is False


def test_tech_run_is_due_once_per_day_from_the_daily_hour(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    assert tech_runner.is_due(conn, datetime(2026, 10, 3, 8, 20)) is True   # never run
    storage.start_run(conn, "2026-10-03T08:20:00", "tech")
    assert tech_runner.is_due(conn, datetime(2026, 10, 3, 9, 20)) is False  # already ran today
    assert tech_runner.is_due(conn, datetime(2026, 10, 4, 8, 20)) is True   # next day


def test_missed_tech_run_is_caught_up_when_the_mac_wakes(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.start_run(conn, "2026-09-17T08:00:01", "tech")
    # Asleep through 08:00 on Oct 3, awake again at 18:00.
    assert tech_runner.is_due(conn, datetime(2026, 10, 3, 18, 20)) is True


def test_pharma_runs_do_not_count_as_tech_runs(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.start_run(conn, "2026-10-03T08:00:00", "pharma")
    assert tech_runner.is_due(conn, datetime(2026, 10, 3, 9, 20)) is True


def test_cli_force_flag():
    assert tech_runner.parse_args([]).force is False
    assert tech_runner.parse_args(["--force"]).force is True
