from __future__ import annotations

import warnings
from urllib.parse import urlparse

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jobfinder import config

# Hosts with broken cert chains. Scoped exception instead of a
# process-wide ssl bypass — everything else stays verified.
INSECURE_HOSTS = {"jobs.takeda.com", "careers.ey.com"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": USER_AGENT,
        # urllib3 2.x auto-negotiates zstd if the zstandard package is
        # installed, but this environment's urllib3+zstandard version
        # pair has a real decode bug on multi-chunk streamed responses
        # ("cannot use a decompressobj multiple times") -- confirmed live
        # against Amazon's careers API. Excluding zstd from what this
        # session advertises support for means servers never send it.
        "Accept-Encoding": "gzip, deflate",
    })
    return session


def fetch(session, url: str, method: str = "get", **kwargs):
    host = urlparse(url).hostname or ""
    verify = host not in INSECURE_HOSTS
    kwargs.setdefault("timeout", config.REQUEST_TIMEOUT)
    kwargs.setdefault("verify", verify)
    if not verify:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            response = getattr(session, method)(url, **kwargs)
    else:
        response = getattr(session, method)(url, **kwargs)
    response.raise_for_status()
    return response
