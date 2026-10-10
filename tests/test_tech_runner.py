from datetime import datetime

import anthropic
import httpx2

from jobfinder import config, enrichment, insights, storage, tech_runner
from jobfinder.models import Job
from tests.conftest import FakeClaude, fake_response, make_insight


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


_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
SCIENTIST = Job("Good Tech Co", "Applied Scientist", "https://good.example/sci", "https://good.example", sector="tech")
SALES = Job("Good Tech Co", "Cloud & AI Sales Specialist", "https://good.example/sales", "https://good.example", sector="tech")
SRE = good_scraper(None)[0]  # "Senior SRE": passes the keyword filter


def _listing(*jobs):
    return lambda session: list(jobs)


def _desc(text="Builds machine learning models in Python."):
    return lambda session, job: text


def test_claude_decides_relevance_and_rejected_postings_are_never_stored(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SCIENTIST, SALES)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc())
    client = FakeClaude(
        fake_response(make_insight(relevant=True, reason="Applied ML research role.")),
        fake_response(make_insight(relevant=False, reason="Sales role.", role_family="Sales/Pre-sales")),
    )
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert result.new_jobs == {"Good Tech Co": [SCIENTIST]}
    assert result.reasons == {SCIENTIST.key: "Applied ML research role."}
    assert storage.get_insight(conn, SALES.key, insights.PROMPT_VERSION)["relevant"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] == 1
    assert result.insight_alert == (True, None)


def test_a_saved_insight_is_reused_without_claude_or_a_fetch(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    first = insights.analyse(FakeClaude(fake_response(make_insight())), SCIENTIST, "d", "tech")
    storage.save_insight(conn, insights.result_row(SCIENTIST, "tech", first, "2026-10-09T08:20:00"))
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SCIENTIST)})

    def no_fetch(session, job):
        raise AssertionError("must not fetch a description for a saved posting")

    monkeypatch.setattr(tech_runner, "posting_description", no_fetch)
    client = FakeClaude()  # any call raises IndexError
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert result.new_jobs == {"Good Tech Co": [SCIENTIST]} and client.calls == []
    assert result.insight_alert == (False, None)


def test_an_outage_falls_back_to_keywords_and_saves_nothing(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SRE, SCIENTIST)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc())
    client = FakeClaude(anthropic.APIConnectionError(request=_REQ), anthropic.APIConnectionError(request=_REQ))
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert result.new_jobs == {"Good Tech Co": [SRE]}  # "Senior SRE" matches the keywords; the scientist doesn't
    assert storage.insight_status_counts(conn) == {}


def test_a_config_error_stops_claude_and_is_reported(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SCIENTIST, SRE)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc())
    auth = anthropic.AuthenticationError("invalid x-api-key",
                                         response=httpx2.Response(401, request=_REQ), body=None)
    client = FakeClaude(auth)
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert len(client.calls) == 1
    assert result.new_jobs == {"Good Tech Co": [SRE]}
    assert result.insight_alert[0] is True and "invalid x-api-key" in result.insight_alert[1]


def test_a_refusal_is_saved_and_the_keyword_decision_stands(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SRE)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc())
    tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00",
                           FakeClaude(fake_response(None, stop_reason="refusal")))
    assert storage.get_insight(conn, SRE.key, insights.PROMPT_VERSION)["status"] == "refused"
    assert conn.execute("SELECT is_active FROM jobs WHERE job_key = ?", (SRE.key,)).fetchone()["is_active"] == 1
    client = FakeClaude()
    tech_runner.run_scrape(conn, None, "2026-10-11T08:20:00", client)  # not retried
    assert client.calls == []


def test_without_a_client_the_run_is_unchanged(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SRE, SCIENTIST)})
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00")
    assert result.new_jobs == {"Good Tech Co": [SRE]}
    assert result.reasons == {} and result.insight_alert == (False, None)
    assert storage.insight_status_counts(conn) == {}


def test_new_relevant_jobs_keep_the_fetched_description(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SCIENTIST)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc("Builds ML models with Python."))
    tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", FakeClaude(fake_response(make_insight())))
    row = conn.execute("""SELECT d.description FROM job_details d JOIN jobs j ON j.id = d.job_id
                          WHERE j.job_key = ?""", (SCIENTIST.key,)).fetchone()
    assert row["description"] == "Builds ML models with Python."
    assert storage.find_unenriched_jobs(conn) == []  # the enrichment pass won't fetch it again


def test_a_failed_fetch_skips_claude_for_that_posting(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SRE)})
    monkeypatch.setattr(tech_runner, "posting_description", lambda session, job: tech_runner.FETCH_FAILED)
    client = FakeClaude()
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert client.calls == [] and result.new_jobs == {"Good Tech Co": [SRE]}


def test_the_daily_cap_falls_back_to_keywords(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    monkeypatch.setattr(config, "INSIGHTS_DAILY_CALL_LIMIT", 1)
    monkeypatch.setattr(tech_runner, "TECH_SCRAPERS", {"Good Tech Co": _listing(SCIENTIST, SRE)})
    monkeypatch.setattr(tech_runner, "posting_description", _desc())
    client = FakeClaude(fake_response(make_insight()))
    result = tech_runner.run_scrape(conn, None, "2026-10-10T08:20:00", client)
    assert len(client.calls) == 1
    assert result.new_jobs == {"Good Tech Co": [SCIENTIST, SRE]}  # SRE kept by keywords


def test_posting_description_uses_the_company_fetcher(monkeypatch):
    job = Job("Microsoft", "Data Scientist", "https://ms.example/1", "p", sector="tech")
    monkeypatch.setattr(enrichment, "fetch_description", lambda session, url: f"desc of {url}")
    assert tech_runner.posting_description(None, job) == "desc of https://ms.example/1"
    no_fetcher = Job("Allianz Partners", "Data Analyst", "https://ap.example/1", "p", sector="tech")
    assert tech_runner.posting_description(None, no_fetcher) is None  # read from the title alone

    def boom(session, url):
        raise RuntimeError("HTTP 503")

    monkeypatch.setattr(enrichment, "fetch_description", boom)
    assert tech_runner.posting_description(None, job) is tech_runner.FETCH_FAILED
