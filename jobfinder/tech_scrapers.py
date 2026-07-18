from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import List
from urllib.parse import urljoin

from jobfinder.http_client import fetch
from jobfinder.models import Job
from jobfinder.scrapers import _sf_pagination_total

# Role-keyword filter, applied before any job is returned from a tech
# scraper. Short/ambiguous tokens (ml, sre, bi) use \b word boundaries so
# they don't match as substrings inside unrelated words (e.g. "html"
# contains "ml", "Responsible" contains "bi") -- verified against both
# real target titles and known false-positive traps during design.
_ROLE_PATTERNS = [
    r"data scien",
    r"machine learning",
    r"\bml\b",
    r"site reliability",
    r"\bsre\b",
    r"devops",
    r"cloud (engineer|architect|platform|infrastructure)",
    r"splunk",
    r"analytics",
    r"data analyst",
    r"business intelligence",
    r"\bbi\b",
]
_ROLE_RE = re.compile("|".join(_ROLE_PATTERNS), re.IGNORECASE)


def matches_target_role(title: str) -> bool:
    return bool(_ROLE_RE.search(title))


# Google's careers search page embeds real job data server-side as a
# Google Closure "AF_initDataCallback({key: 'ds:1', ..., data: [...]})"
# chunk -- not a clean JSON API, but the `data` value itself is valid
# JSON once extracted (its strings use \uXXXX escapes, same as JSON).
# Confirmed live during design: real Ireland postings including an actual
# "Senior Software Engineer, Site Reliability Engineering, Cloud Storage"
# role. Pagination is `&page=N`, but the server does NOT signal "no more
# pages" by returning empty -- past the last real page it just keeps
# re-serving the last valid page's content. So termination is detected by
# tracking each page's first job ID: if it repeats a previously-seen ID,
# the server has clamped to an already-visited page and scraping stops.
GOOGLE_SEARCH = "https://careers.google.com/jobs/results/?location=Ireland&page="
GOOGLE_PORTAL = "https://careers.google.com/jobs/results/?location=Ireland"


def _extract_google_data_chunk(html: str) -> list:
    marker = "key: 'ds:1'"
    start = html.find(marker)
    if start == -1:
        return []
    data_start = html.find("data:", start) + len("data:")
    depth = 0
    end = None
    in_string = False
    escape = False
    for i in range(data_start, len(html)):
        ch = html[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return []
    return json.loads(html[data_start:end])


def google(session) -> List[Job]:
    # Live-verified (2026-07-18): when `&page=N` is present, the ds:1 chunk's
    # `data` value is `[jobs_list, None, total_count, page_size]` -- NOT a
    # flat list of job entries. (A request with no `page` param at all
    # returns a flatter shape; this scraper always passes `page`, so it
    # always gets the nested one.) `total_count` makes pagination exact --
    # no need for the "did this page repeat?" heuristic an earlier version
    # of this scraper used.
    jobs = []
    page = 1
    fetched = 0
    while True:
        resp = fetch(session, f"{GOOGLE_SEARCH}{page}")
        payload = _extract_google_data_chunk(resp.content.decode("utf-8"))
        if not payload:
            break
        batch = payload[0] or []
        if not batch:
            break
        for entry in batch:
            job_id, title, apply_url = entry[0], entry[1], entry[2]
            if matches_target_role(title):
                jobs.append(Job("Google", title, apply_url, GOOGLE_PORTAL, sector="tech"))
        fetched += len(batch)
        total = payload[2] if len(payload) > 2 and isinstance(payload[2], int) else None
        page += 1
        if total is not None and fetched >= total:
            break
        if page > 50:  # safety cap -- generous given real totals seen (~130 jobs / 20 per page)
            raise RuntimeError("Google pagination exceeded safety cap of 50 pages")
    return jobs


# AIB (Pratik's employer) runs the same SAP SuccessFactors "job2web"
# platform as Grifols/Leo Pharma in jobfinder/scrapers.py -- confirmed
# live during design: identical data-row/jobTitle-link/paginationLabel
# markup, real live postings including "Fraud Data Scientist". No
# location filter needed -- AIB is an Ireland-only bank.
AIB_BASE = "https://jobs.aib.ie"
AIB_SEARCH = "https://jobs.aib.ie/aib/go/SearchAllJobs/9605800/?startrow="
AIB_PORTAL = "https://jobs.aib.ie/aib/go/SearchAllJobs/9605800/"


def aib(session) -> List[Job]:
    jobs = []
    offset = 0
    total = None
    while total is None or offset < total:
        resp = fetch(session, f"{AIB_SEARCH}{offset}")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.content, "lxml")
        rows = soup.find_all("tr", class_="data-row")
        if not rows:
            break
        for row in rows:
            link = row.find("a", class_="jobTitle-link")
            if not link:
                continue
            title = link.get_text(strip=True)
            if matches_target_role(title):
                jobs.append(Job(
                    "AIB", title, urljoin(AIB_BASE, link["href"]), AIB_PORTAL,
                    sector="tech",
                ))
        label = soup.find("span", class_="paginationLabel")
        parsed_total = _sf_pagination_total(label, offset)
        total = parsed_total if parsed_total is not None else len(rows)
        offset += len(rows)
    return jobs


# Live-verified (2026-07-18): jobs.careers.microsoft.com now redirects to
# apply.careers.microsoft.com, which runs on Eightfold.ai (tenant
# "microsoft.com") -- a different platform than Microsoft's older public
# API this scraper originally guessed at (that older host,
# gcsservices.careers.microsoft.com, is now dangling DNS pointing at a
# generic Azure CDN edge with no valid cert for this hostname -- fully
# dead, not a network fluke). This is the exact same Eightfold "pcsx"
# search API that jobfinder/scrapers.py's bms() already uses for BMS (a
# different Eightfold tenant) -- the officially-documented
# /api/apply/v2/jobs path 403s ("Not authorized for PCSX"), but this is
# the endpoint the careers SPA itself calls, and it works anonymously.
MSFT_API = "https://apply.careers.microsoft.com/api/pcsx/search"
MSFT_BASE = "https://apply.careers.microsoft.com"
MSFT_PORTAL = "https://apply.careers.microsoft.com/careers?domain=microsoft.com&location=Ireland"


def microsoft(session) -> List[Job]:
    jobs = []
    start = 0
    while True:
        resp = fetch(session, MSFT_API, params={
            "domain": "microsoft.com", "query": "", "location": "Ireland",
            "start": start, "sort_by": "distance", "filter_include_remote": 1,
        })
        data = resp.json().get("data", {})
        positions = data.get("positions", [])
        for pos in positions:
            title = pos.get("name", "").strip()
            if not matches_target_role(title):
                continue
            jobs.append(Job(
                "Microsoft", title,
                urljoin(MSFT_BASE, pos.get("positionUrl", "")),
                MSFT_PORTAL, sector="tech",
            ))
        start += len(positions)
        if not positions or start >= data.get("count", 0):
            break
    return jobs


TECH_SCRAPERS = OrderedDict([
    ("Google", google),
    ("Microsoft", microsoft),
    ("AIB", aib),
])
