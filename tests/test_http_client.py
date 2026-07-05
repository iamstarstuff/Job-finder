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


def test_fetch_raises_on_http_error():
    fake = FakeSession({"https://example.com": FakeResponse(status_code=500)})
    try:
        http_client.fetch(fake, "https://example.com/x")
        assert False, "should have raised"
    except RuntimeError:
        pass
