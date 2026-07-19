from jobfinder import http_client
from tests.conftest import FakeSession, FakeResponse


def test_session_has_retry_adapter():
    session = http_client.build_session()
    adapter = session.get_adapter("https://example.com")
    assert adapter.max_retries.total == 3


def test_fetch_sets_timeout_and_verify():
    fake = FakeSession({"https://example.com": FakeResponse(b"ok")})
    http_client.fetch(fake, "https://example.com/page")
    _, _, kwargs = fake.calls[0]
    assert kwargs["timeout"] == 20
    assert kwargs["verify"] is True


def test_fetch_disables_verify_only_for_insecure_hosts():
    fake = FakeSession({"https://jobs.takeda.com": FakeResponse(b"ok")})
    http_client.fetch(fake, "https://jobs.takeda.com/search")
    _, _, kwargs = fake.calls[0]
    assert kwargs["verify"] is False


def test_fetch_disables_verify_for_ey_too():
    fake = FakeSession({"https://careers.ey.com": FakeResponse(b"ok")})
    http_client.fetch(fake, "https://careers.ey.com/ey/search/")
    _, _, kwargs = fake.calls[0]
    assert kwargs["verify"] is False


def test_session_excludes_zstd_from_accept_encoding():
    # urllib3 2.x + the zstandard package installed in this environment
    # (0.19.0) has a real decode bug on multi-chunk streamed responses
    # ("cannot use a decompressobj multiple times") -- confirmed live
    # against a real zstd-serving host (Amazon's careers API) during
    # Round 2 manual verification. Excluding zstd from what this session
    # advertises support for means servers never send it, sidestepping
    # the bug entirely rather than working around it per-request.
    session = http_client.build_session()
    accept_encoding = session.headers.get("Accept-Encoding", "")
    assert "zstd" not in accept_encoding.lower()


def test_fetch_raises_on_http_error():
    fake = FakeSession({"https://example.com": FakeResponse(status_code=500)})
    try:
        http_client.fetch(fake, "https://example.com/x")
        assert False, "should have raised"
    except RuntimeError:
        pass
