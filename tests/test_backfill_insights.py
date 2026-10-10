import json
from types import SimpleNamespace

import backfill_insights
from jobfinder import config, insights, storage
from jobfinder.models import Job
from tests.conftest import fake_response, make_insight

SCI = Job("AWS", "Applied Scientist", "https://amazon.jobs/1", "https://amazon.jobs", sector="tech")
QC = Job("Pfizer", "QC Analyst", "https://pfizer.example/1", "p")


class FakeBatches:
    def __init__(self, results):
        self._results = results
        self.created = []

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id="msgbatch_1")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended",
                               request_counts=SimpleNamespace(processing=0, succeeded=1, errored=1))

    def results(self, batch_id):
        return iter(self._results)


class FakeBatchClient:
    def __init__(self, results=()):
        self.messages = SimpleNamespace(batches=FakeBatches(list(results)))

    def with_options(self, **kwargs):
        return self


def _succeeded(custom_id, insight):
    message = SimpleNamespace(model="claude-sonnet-5-5", stop_reason="end_turn", stop_details=None,
                              usage=fake_response().usage,
                              content=[SimpleNamespace(type="text", text=insight.model_dump_json())])
    return SimpleNamespace(custom_id=custom_id, result=SimpleNamespace(type="succeeded", message=message))


def _setup(tmp_path, monkeypatch, client, items):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(config, "BACKFILL_STATE_PATH", tmp_path / "backfill_batch.json")
    monkeypatch.setattr(insights, "build_client", lambda: client)
    monkeypatch.setattr(backfill_insights, "collect", lambda conn, session: items)
    monkeypatch.setattr(backfill_insights, "build_session", lambda: None)


def test_dry_run_sends_nothing(tmp_path, monkeypatch, capsys):
    client = FakeBatchClient()
    _setup(tmp_path, monkeypatch, client, [(SCI, "desc", "tech")])
    assert backfill_insights.main([]) == 0
    assert client.messages.batches.created == []
    out = capsys.readouterr().out
    assert "Dry run" in out and "estimated $" in out
    assert not config.BACKFILL_STATE_PATH.exists()


def test_yes_submits_and_saves_results_by_custom_id(tmp_path, monkeypatch):
    errored = SimpleNamespace(custom_id="job-00000", result=SimpleNamespace(type="errored"))
    client = FakeBatchClient([_succeeded("job-00001", make_insight(relevant=None, reason=None,
                                                                    role_family="Quality")), errored])
    _setup(tmp_path, monkeypatch, client, [(SCI, "desc", "tech"), (QC, "QC role", "pharma")])
    assert backfill_insights.main(["--yes"]) == 0
    assert len(client.messages.batches.created[0]) == 2
    conn = storage.connect(config.DB_PATH)
    saved = storage.get_insight(conn, QC.key, insights.PROMPT_VERSION)
    assert saved["role_family"] == "Quality" and saved["via_batch"] == 1 and saved["sector"] == "pharma"
    assert storage.get_insight(conn, SCI.key, insights.PROMPT_VERSION) is None  # errored: left for the regular passes
    state = json.loads(config.BACKFILL_STATE_PATH.read_text())
    assert state["batch_id"] == "msgbatch_1" and state["items"]["job-00001"]["url"] == QC.url


def test_refused_batch_results_are_left_for_the_realtime_passes(tmp_path, monkeypatch):
    refused = SimpleNamespace(model="claude-sonnet-5-5", stop_reason="refusal", stop_details=None,
                              usage=fake_response().usage, content=[])
    client = FakeBatchClient([SimpleNamespace(custom_id="job-00000",
                                              result=SimpleNamespace(type="succeeded", message=refused))])
    _setup(tmp_path, monkeypatch, client, [(SCI, "desc", "tech")])
    assert backfill_insights.main(["--yes"]) == 0
    conn = storage.connect(config.DB_PATH)
    assert storage.get_insight(conn, SCI.key, insights.PROMPT_VERSION) is None


def test_yes_without_a_key_stops_before_sending(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, None, [(SCI, "desc", "tech")])
    assert backfill_insights.main(["--yes"]) == 1


def test_tech_posting_items_skip_saved_postings_and_failed_fetches(tmp_path, monkeypatch):
    conn = storage.connect(tmp_path / "t.db")
    saved = Job("AWS", "Saved", "https://amazon.jobs/saved", "p", sector="tech")
    broken = Job("AWS", "Broken fetch", "https://amazon.jobs/broken", "p", sector="tech")
    row = insights.result_row(saved, "tech", insights.parse_batch_message(
        _succeeded("x", make_insight()).result.message, "tech", False), "2026-10-10T08:00:00")
    storage.save_insight(conn, row)
    monkeypatch.setattr(backfill_insights, "TECH_SCRAPERS",
                        {"AWS": lambda session: [SCI, saved, broken, SCI]})
    monkeypatch.setattr(backfill_insights.tech_runner, "posting_description",
                        lambda session, job: backfill_insights.tech_runner.FETCH_FAILED
                        if job is broken else "desc")
    items = backfill_insights.tech_posting_items(conn, None, skip_keys=set())
    assert [(job.title, sector) for job, _, sector in items] == [("Applied Scientist", "tech")]
