import anthropic
import httpx2
import pytest

from jobfinder import insights
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
