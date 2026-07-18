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
