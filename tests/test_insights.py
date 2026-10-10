import anthropic
import httpx2
import pytest

from jobfinder import config, insights, storage
from jobfinder.models import Job
from tests.conftest import FakeClaude, fake_response, make_insight

JOB = Job("AWS", "Applied Scientist, AI Ops", "https://amazon.jobs/1", "https://amazon.jobs", sector="tech")
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, code):
    return cls("boom", response=httpx2.Response(code, request=_REQ), body=None)


def test_request_carries_model_effort_schema_prompt_and_fallback():
    client = FakeClaude(fake_response(make_insight()))
    insights.analyse(client, JOB, "Build ML models for operations.", "tech")
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["output_format"] is insights.Insight
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["fallbacks"] == "default"
    assert call["system"] == [{"type": "text", "text": insights.SYSTEM_PROMPT,
                               "cache_control": {"type": "ephemeral"}}]
    content = call["messages"][0]["content"]
    assert "Sector: tech" in content and "Company: AWS" in content
    assert "<posting>\nBuild ML models for operations.\n</posting>" in content


def test_title_only_request_when_there_is_no_description():
    client = FakeClaude(fake_response(make_insight()))
    result = insights.analyse(client, JOB, None, "tech")
    content = client.calls[0]["messages"][0]["content"]
    assert "<posting>" not in content and "No description is available" in content
    assert result.title_only is True


def test_result_carries_usage_and_cost():
    client = FakeClaude(fake_response(make_insight(), input_tokens=1000, output_tokens=200,
                                      cache_write=700, cache_read=0))
    result = insights.analyse(client, JOB, "desc", "tech")
    assert result.insight.relevant is True and result.model == "claude-sonnet-5-5"
    assert result.usage.input_tokens == 1700 and result.usage.output_tokens == 200
    # 1000 x $2 + 200 x $10 + 700 cache-write tokens x $2.50, per million
    assert result.usage.cost_usd == pytest.approx(0.00575)


def test_batch_cost_is_half_and_unlisted_models_use_model_rates():
    usage = fake_response().usage  # 1000 in, 200 out
    assert insights.usage_cost("claude-sonnet-5-5", usage, batch=True).cost_usd == pytest.approx(0.002)
    assert insights.usage_cost("claude-unknown-9", usage).cost_usd == pytest.approx(0.004)


def test_pharma_results_drop_relevance():
    client = FakeClaude(fake_response(make_insight(relevant=True, reason="x", role_family="Quality")))
    result = insights.analyse(client, Job("Pfizer", "QC Analyst", "u", "p"), "desc", "pharma")
    assert result.insight.relevant is None and result.insight.reason is None


def test_refusal_raises_refused_with_its_cost():
    client = FakeClaude(fake_response(None, stop_reason="refusal", category="cyber"))
    with pytest.raises(insights.InsightRefused) as caught:
        insights.analyse(client, JOB, "desc", "tech")
    assert caught.value.status == "refused" and caught.value.usage.cost_usd > 0
    assert "cyber" in str(caught.value)


def test_max_tokens_raises_bad_output_with_its_cost():
    client = FakeClaude(fake_response(None, stop_reason="max_tokens"))
    with pytest.raises(insights.InsightBadOutput) as caught:
        insights.analyse(client, JOB, "desc", "tech")
    assert caught.value.status == "failed" and caught.value.usage.cost_usd > 0


def test_tech_reply_without_a_relevance_decision_is_bad_output():
    client = FakeClaude(fake_response(make_insight(relevant=None)))
    with pytest.raises(insights.InsightBadOutput):
        insights.analyse(client, JOB, "desc", "tech")


@pytest.mark.parametrize("error, expected", [
    (anthropic.APIConnectionError(request=_REQ), insights.InsightUnavailable),
    (anthropic.APITimeoutError(request=_REQ), insights.InsightUnavailable),
    (_status_error(anthropic.RateLimitError, 429), insights.InsightUnavailable),
    (_status_error(anthropic.OverloadedError, 529), insights.InsightUnavailable),
    (_status_error(anthropic.InternalServerError, 500), insights.InsightUnavailable),
    (_status_error(anthropic.AuthenticationError, 401), insights.InsightConfigError),
    (_status_error(anthropic.PermissionDeniedError, 403), insights.InsightConfigError),
    (_status_error(anthropic.NotFoundError, 404), insights.InsightConfigError),
    (_status_error(anthropic.APIStatusError, 402), insights.InsightConfigError),
    (_status_error(anthropic.BadRequestError, 400), insights.InsightConfigError),
    (ValueError("reply did not match the schema"), insights.InsightBadOutput),
])
def test_sdk_errors_map_to_insight_errors(error, expected):
    with pytest.raises(expected):
        insights.analyse(FakeClaude(error), JOB, "desc", "tech")


def test_build_client_is_none_without_a_key():
    assert insights.build_client() is None


def test_build_client_with_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(insights.build_client(), anthropic.Anthropic)


NOW = "2026-10-10T08:20:00"


def _conn(tmp_path):
    return storage.connect(tmp_path / "t.db")


def test_result_row_fills_every_column(tmp_path):
    result = insights.analyse(FakeClaude(fake_response(make_insight(
        salary=insights.Salary(min=70000, max=90000, currency="EUR", period="year")))), JOB, "d", "tech")
    row = insights.result_row(JOB, "tech", result, NOW)
    assert set(row) == set(storage.INSIGHT_COLUMNS)
    assert row["job_key"] == JOB.key and row["status"] == "ok" and row["relevant"] == 1
    assert row["skills"] == '["Python", "PyTorch"]' and row["salary_currency"] == "EUR"
    assert row["prompt_version"] == insights.PROMPT_VERSION and row["via_batch"] == 0


def test_runner_saves_an_ok_row_and_counts_the_call(tmp_path):
    conn = _conn(tmp_path)
    runner = insights.InsightRunner(conn, FakeClaude(fake_response(make_insight())), NOW)
    row = runner.classify(JOB, "desc", "tech")
    saved = storage.get_insight(conn, JOB.key, insights.PROMPT_VERSION)
    assert row["status"] == saved["status"] == "ok" and saved["relevant"] == 1
    assert runner.billed == 1 and runner.remaining == config.INSIGHTS_DAILY_CALL_LIMIT - 1
    assert runner.spent == pytest.approx(saved["cost_usd"])


def test_runner_is_inactive_without_a_client(tmp_path):
    runner = insights.InsightRunner(_conn(tmp_path), None, NOW)
    assert runner.active is False and runner.classify(JOB, "desc", "tech") is None
    assert runner.alert() == (False, None)


def test_runner_saves_refused_and_failed_rows_with_their_cost(tmp_path):
    conn = _conn(tmp_path)
    other = Job("AWS", "Systems Engineer", "https://amazon.jobs/2", "p", sector="tech")
    runner = insights.InsightRunner(conn, FakeClaude(
        fake_response(None, stop_reason="refusal"), fake_response(None, stop_reason="max_tokens")), NOW)
    runner.classify(JOB, "desc", "tech")
    runner.classify(other, None, "tech")
    assert storage.get_insight(conn, JOB.key, 1)["status"] == "refused"
    failed = storage.get_insight(conn, other.key, 1)
    assert failed["status"] == "failed" and failed["title_only"] == 1 and failed["cost_usd"] > 0
    assert runner.billed == 2


def test_runner_stops_after_three_outages_in_a_row(tmp_path):
    conn = _conn(tmp_path)
    client = FakeClaude(*[anthropic.APIConnectionError(request=_REQ) for _ in range(3)])
    runner = insights.InsightRunner(conn, client, NOW)
    for _ in range(4):
        assert runner.classify(JOB, "desc", "tech") is None
    assert len(client.calls) == 3 and runner.active is False
    assert storage.insight_status_counts(conn) == {}
    assert runner.alert() == (False, None)  # never reached the API: no alert either way


def test_runner_stops_after_a_config_error_and_reports_it(tmp_path):
    client = FakeClaude(_status_error(anthropic.AuthenticationError, 401))
    runner = insights.InsightRunner(_conn(tmp_path), client, NOW)
    assert runner.classify(JOB, "desc", "tech") is None
    assert runner.active is False
    report, error = runner.alert()
    assert report is True and "boom" in error


def test_runner_keeps_to_the_daily_cap(tmp_path):
    conn = _conn(tmp_path)
    earlier = insights.result_row(Job("X", "t", "https://x/1", "p"), "tech",
                                  insights.analyse(FakeClaude(fake_response(make_insight())), JOB, "d", "tech"),
                                  "2026-10-10T07:00:00")
    storage.save_insight(conn, earlier)                                                # counts
    storage.save_insight(conn, {**earlier, "job_key": "https://x/2", "via_batch": 1})  # batch: doesn't
    client = FakeClaude(fake_response(make_insight()))
    runner = insights.InsightRunner(conn, client, NOW, daily_limit=2)
    assert runner.remaining == 1
    assert runner.classify(JOB, "desc", "tech") is not None
    assert runner.classify(Job("AWS", "Other", "https://amazon.jobs/3", "p"), "desc", "tech") is None
    assert len(client.calls) == 1


def test_alert_reports_recovery_once_a_call_goes_through(tmp_path):
    runner = insights.InsightRunner(_conn(tmp_path), FakeClaude(fake_response(make_insight())), NOW)
    runner.classify(JOB, "desc", "tech")
    assert runner.alert() == (True, None)
