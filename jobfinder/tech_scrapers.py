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


# Workday CXS API. Facet GUIDs are Workday location-facet IDs; unlike the
# shared platform-wide "Ireland" country ID some tenants expose (see
# Accenture below), most tenants only expose per-city location IDs, which
# are tenant-specific and were found by inspecting each tenant's own facet
# list during design (POST the jobs endpoint with an empty search --
# Workday returns available facet values, including their IDs, alongside
# results).
MASTERCARD_API = "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs"
MASTERCARD_BASE = "https://mastercard.wd1.myworkdayjobs.com/en-US/CorporateCareers"
MASTERCARD_FACETS = {"locations": ["8eab563831bf10acb918385326cff456", "c17ea515bfcf010108dc84da21c80000"]}


def mastercard(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, MASTERCARD_API, method="post", json={
            "appliedFacets": MASTERCARD_FACETS, "limit": limit, "offset": offset, "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            title = posting.get("title", "")
            if matches_target_role(title):
                jobs.append(Job(
                    "Mastercard", title,
                    MASTERCARD_BASE + posting.get("externalPath", ""), MASTERCARD_BASE,
                    sector="tech",
                ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Accenture's tenant exposes a "locationCountry" facet with the same
# shared, platform-wide Workday GUID for Ireland that PFIZER_FACETS/
# VIATRIS_FACETS already use in jobfinder/scrapers.py -- confirmed by
# finding this exact GUID under this tenant's own facet list next to the
# "Ireland" label. A plain searchText:"Ireland" free-text search does NOT
# filter by location on this tenant (verified live: it matched unrelated
# global postings whose descriptions merely mentioned Ireland) -- the
# facet is required.
ACCENTURE_API = "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs"
ACCENTURE_BASE = "https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers"
ACCENTURE_FACETS = {"locationCountry": ["04a05835925f45b3a59406a2a6b72c8a"]}


def accenture(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, ACCENTURE_API, method="post", json={
            "appliedFacets": ACCENTURE_FACETS, "limit": limit, "offset": offset, "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            title = posting.get("title", "")
            if matches_target_role(title):
                jobs.append(Job(
                    "Accenture", title,
                    ACCENTURE_BASE + posting.get("externalPath", ""), ACCENTURE_BASE,
                    sector="tech",
                ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Intel's Ireland presence is a single site (Leixlip), so this uses that
# specific city-level location facet ID rather than a country-level one.
INTEL_API = "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs"
INTEL_BASE = "https://intel.wd1.myworkdayjobs.com/en-US/External"
INTEL_FACETS = {"locations": ["1e4a4eb3adf101424c5a8574bf8175cd"]}


def intel(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, INTEL_API, method="post", json={
            "appliedFacets": INTEL_FACETS, "limit": limit, "offset": offset, "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            title = posting.get("title", "")
            if matches_target_role(title):
                jobs.append(Job(
                    "Intel", title,
                    INTEL_BASE + posting.get("externalPath", ""), INTEL_BASE,
                    sector="tech",
                ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Eightfold "pcsx" API -- identical pattern to bms()/microsoft(), just a
# different tenant domain. Citibank's public-facing jobs.citi.com runs on
# a different platform (Symphony Talent/TalentBrew) with no discoverable
# API, but confirmed live to show the same underlying postings as this
# feed (a job found on jobs.citi.com matched by title here, under a
# different internal ID) -- TalentBrew is a separate branded frontend
# Citi also maintains, not an independent data source.
CITIBANK_API = "https://citi.eightfold.ai/api/pcsx/search"
CITIBANK_BASE = "https://citi.eightfold.ai"
CITIBANK_PORTAL = "https://citi.eightfold.ai/careers?domain=citi.com&location=Ireland"


def citibank(session) -> List[Job]:
    jobs = []
    start = 0
    while True:
        resp = fetch(session, CITIBANK_API, params={
            "domain": "citi.com", "query": "", "location": "Ireland",
            "start": start, "sort_by": "distance", "filter_include_remote": 1,
        })
        data = resp.json().get("data", {})
        positions = data.get("positions", [])
        for pos in positions:
            title = pos.get("name", "").strip()
            if matches_target_role(title):
                jobs.append(Job(
                    "Citibank", title,
                    urljoin(CITIBANK_BASE, pos.get("positionUrl", "")),
                    CITIBANK_PORTAL, sector="tech",
                ))
        start += len(positions)
        if not positions or start >= data.get("count", 0):
            break
    return jobs


# Phenom People "widgets" API -- identical pattern to MSD's
# _msd_payload()/msd() in jobfinder/scrapers.py. This feed covers the
# whole Allianz Group, not just Allianz Partners -- confirmed live that
# most Ireland postings belong to sibling entities ("Allianz Global Life
# dac", "Allianz Technology SE Ireland Branch", etc). Allianz Partners'
# own postings are tagged either "ALLIANZ PARTNERS" or its legacy
# pre-rebrand name "AWP" (Allianz Worldwide Partners) in the
# employingEntity field -- both must be checked. Unlike most scrapers in
# this codebase, applyUrl is already a complete absolute URL, so no
# urljoin is needed here.
ALLIANZ_API = "https://careers.allianz.com/widgets"


def _allianz_payload(offset: int, size: int) -> dict:
    return {
        "lang": "en", "deviceType": "desktop", "country": "gb",
        "pageName": "search-results", "ddoKey": "refineSearch",
        "sortBy": "", "subsearch": "", "from": offset, "jobs": True,
        "counts": True, "all_fields": ["category", "country", "state", "city", "type", "company"],
        "size": size, "clearAll": False, "jdsource": "facets",
        "isSliderEnable": False, "pageId": "page10", "siteType": "external",
        "keywords": "", "global": True,
        "selected_fields": {"country": ["Ireland"]}, "locationData": {},
    }


def _is_allianz_partners_entity(entity: str) -> bool:
    entity = (entity or "").upper()
    return "ALLIANZ PARTNERS" in entity or "AWP" in entity


def allianz_partners(session) -> List[Job]:
    jobs = []
    offset = 0
    size = 20
    while True:
        resp = fetch(session, ALLIANZ_API, method="post", json=_allianz_payload(offset, size))
        payload = resp.json().get("refineSearch", {})
        batch = payload.get("data", {}).get("jobs", [])
        for item in batch:
            title = item.get("title", "").strip()
            if matches_target_role(title) and _is_allianz_partners_entity(item.get("employingEntity")):
                jobs.append(Job(
                    "Allianz Partners", title, item.get("applyUrl", ""),
                    ALLIANZ_API, sector="tech",
                ))
        offset += len(batch)
        if not batch or offset >= payload.get("totalHits", 0):
            break
    return jobs


TECH_SCRAPERS = OrderedDict([
    ("Google", google),
    ("Microsoft", microsoft),
    ("AIB", aib),
])
