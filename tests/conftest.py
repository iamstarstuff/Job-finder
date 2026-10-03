from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_dry_run_from_shell(monkeypatch):
    # A development shell may export JOBFINDER_DRY_RUN; tests opt in explicitly.
    monkeypatch.delenv("JOBFINDER_DRY_RUN", raising=False)


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
