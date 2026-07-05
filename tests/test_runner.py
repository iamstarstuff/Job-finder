from jobfinder import runner, storage
from jobfinder.models import Job


def good_scraper(session):
    return [Job("Good Co", "Engineer", "https://good.example/1", "https://good.example")]


def bad_scraper(session):
    raise RuntimeError("layout changed")


def empty_scraper(session):
    return []


def test_failures_are_captured_not_swallowed(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(runner, "SCRAPERS", {"Good Co": good_scraper, "Bad Co": bad_scraper})
    result = runner.run_scrape(conn, session=None, now="2026-07-05T10:00:00")
    assert "Bad Co" in result.failures
    assert "layout changed" in result.failures["Bad Co"]
    assert result.new_jobs == {"Good Co": [good_scraper(None)[0]]}


def test_zero_jobs_after_having_jobs_raises_warning(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(runner, "SCRAPERS", {"Good Co": good_scraper})
    runner.run_scrape(conn, session=None, now="2026-07-05T10:00:00")
    monkeypatch.setattr(runner, "SCRAPERS", {"Good Co": empty_scraper})
    result = runner.run_scrape(conn, session=None, now="2026-07-05T11:00:00")
    assert result.zero_warnings == ["Good Co"]


def test_failed_company_jobs_are_not_deactivated(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(runner, "SCRAPERS", {"Good Co": good_scraper})
    runner.run_scrape(conn, session=None, now="2026-07-05T10:00:00")
    monkeypatch.setattr(runner, "SCRAPERS", {"Good Co": bad_scraper})
    runner.run_scrape(conn, session=None, now="2026-07-05T11:00:00")
    row = conn.execute("SELECT is_active FROM jobs WHERE company='Good Co'").fetchone()
    assert row["is_active"] == 1  # failure must not mark jobs as vanished
