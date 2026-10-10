from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _no_dry_run_from_shell(monkeypatch):
    # A development shell may export JOBFINDER_DRY_RUN; tests opt in explicitly.
    monkeypatch.delenv("JOBFINDER_DRY_RUN", raising=False)


@pytest.fixture(autouse=True)
def _no_claude_api(monkeypatch, tmp_path):
    # No test may ever reach the real Claude API: drop any key the shell
    # exports and point the key file at a path that doesn't exist.
    from jobfinder import config
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY_FILE", tmp_path / "no_anthropic_api_key.txt")


class FakeResponse:
    def __init__(self, content=b"", json_data=None, status_code=200):
        self.content = content
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Maps URL prefix -> FakeResponse; records calls for assertions."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def _lookup(self, url):
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResponse(status_code=404)

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self._lookup(url)

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self._lookup(url)


class FakeClaude:
    """Stands in for anthropic.Anthropic: beta.messages.parse() records each
    call's kwargs and returns -- or raises -- the next queued outcome. An
    unexpected extra call fails loudly with IndexError."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def fake_response(parsed=None, stop_reason="end_turn", model="claude-sonnet-5-5",
                  input_tokens=1000, output_tokens=200, cache_write=0, cache_read=0, category=None):
    """The shape of a beta.messages.parse() response that insights.analyse() reads."""
    return SimpleNamespace(
        parsed_output=parsed, stop_reason=stop_reason, model=model,
        stop_details=SimpleNamespace(category=category) if stop_reason == "refusal" else None,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens,
                              cache_creation_input_tokens=cache_write,
                              cache_read_input_tokens=cache_read),
    )


def make_insight(**overrides):
    from jobfinder.insights import Insight
    fields = dict(relevant=True, reason="Machine learning engineering role.", role_family="ML/AI",
                  seniority="Senior", min_years_experience=5, skills=["Python", "PyTorch"],
                  required_languages=[], work_mode="hybrid", contract_type="permanent", salary=None)
    fields.update(overrides)
    return Insight(**fields)


def save_reading(conn, job, **fields):
    """Save a status-'ok' Claude reading for `job` (already in `jobs`) with
    sensible defaults; tests pass only the fields they care about, using
    job_insights column names. skills/required_languages take Python lists."""
    from jobfinder import insights, storage
    row = dict.fromkeys(storage.INSIGHT_COLUMNS)
    row.update(
        job_key=job.key, sector=job.sector, company=job.company, title=job.title, status="ok",
        relevant=1 if job.sector == "tech" else None,
        reason="Fits the target areas." if job.sector == "tech" else None,
        role_family="ML/AI" if job.sector == "tech" else "Quality",
        seniority="Not stated", skills=[], required_languages=[],
        work_mode="not_stated", contract_type="not_stated", title_only=0,
        model="claude-sonnet-5-5", prompt_version=insights.PROMPT_VERSION,
        input_tokens=1000, output_tokens=200, cost_usd=0.004, via_batch=0,
        classified_at="2026-10-10T08:00:00",
    )
    row.update(fields)
    row["skills"] = json.dumps(list(row["skills"]))
    row["required_languages"] = json.dumps(list(row["required_languages"]))
    storage.save_insight(conn, row)
