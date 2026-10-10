from __future__ import annotations

import json
import re
from collections import OrderedDict
from typing import List
from urllib.parse import urlencode, urljoin

from jobfinder.http_client import fetch
from jobfinder.models import Job
from jobfinder.scrapers import _scrape_successfactors

# Role-keyword filter. Tech scrapers return EVERY Ireland/remote posting;
# tech_runner applies this filter afterwards, so it can tell "the listing
# is empty" (possible layout change) apart from "nothing matched" (a
# genuine zero that must close the company's old matching jobs).
# Short/ambiguous tokens (ml, sre, bi) use \b word boundaries so they
# don't match as substrings inside unrelated words (e.g. "html" contains
# "ml", "Responsible" contains "bi") -- verified against both real target
# titles and known false-positive traps during design.
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
    r"\bbi\b(?!-)",  # "BI Analyst" yes, "Bi-Lingual" no
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
    return _scrape_successfactors(session, "AIB", AIB_SEARCH, AIB_BASE, AIB_PORTAL, sector="tech")


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
            if _is_allianz_partners_entity(item.get("employingEntity")):
                jobs.append(Job(
                    "Allianz Partners", title, item.get("applyUrl", ""),
                    ALLIANZ_API, sector="tech",
                ))
        offset += len(batch)
        if not batch or offset >= payload.get("totalHits", 0):
            break
    return jobs


# Same SAP SuccessFactors "job2web" platform as aib() (Round 1) and
# grifols()/leo_pharma() in jobfinder/scrapers.py -- identical markup.
# careers.ey.com has a broken TLS cert chain from this environment,
# handled transparently by INSECURE_HOSTS in jobfinder/http_client.py
# (Task 1) -- no cert-related code needed here.
EY_BASE = "https://careers.ey.com"
EY_SEARCH = "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch=Ireland&startrow="
EY_PORTAL = "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch=Ireland"


def ey(session) -> List[Job]:
    return _scrape_successfactors(session, "EY", EY_SEARCH, EY_BASE, EY_PORTAL, sector="tech")


# Amazon runs its own JSON search API -- not a third-party ATS. The
# `.json` suffix on the same URL structure the human-facing search page
# uses returns a clean JSON payload. country=IRL is the correct location
# filter -- loc_query=Ireland and location=Ireland (plausible-looking
# alternatives) both silently return unfiltered global results (verified
# live). result_limit cannot exceed 100 -- above that the API returns
# {"jobs": null, "hits": 0} rather than an HTTP error, so a missing/None
# jobs list is treated as a hard stop here, matching that ceiling never
# being crossed since this always requests exactly 100.
AMAZON_API = "https://www.amazon.jobs/en/search.json"
AMAZON_BASE = "https://www.amazon.jobs"


def _amazon_search(session, want_aws: bool) -> List[Job]:
    company = "AWS" if want_aws else "Amazon"
    jobs = []
    offset = 0
    limit = 100
    while True:
        resp = fetch(session, AMAZON_API, params={
            "base_query": "", "country": "IRL", "offset": offset, "result_limit": limit,
        })
        data = resp.json()
        postings = data.get("jobs") or []
        if not postings:
            break
        for posting in postings:
            title = posting.get("title", "")
            is_aws = posting.get("business_category") == "aws"
            if is_aws != want_aws:
                continue
            jobs.append(Job(
                company, title,
                urljoin(AMAZON_BASE, posting.get("job_path", "")), AMAZON_BASE,
                sector="tech",
            ))
        offset += len(postings)
        if offset >= data.get("hits", 0):
            break
    return jobs


def amazon(session) -> List[Job]:
    return _amazon_search(session, want_aws=False)


def aws(session) -> List[Job]:
    return _amazon_search(session, want_aws=True)


# Stripe rebuilt its careers site (by 2026-10): stripe.com/jobs/search now
# redirects to stripe.com/careers/search, a Next.js page whose old
# table markup is gone -- the previous scraper silently returned zero.
# The page embeds the complete global job index as JSON in __NEXT_DATA__
# (confirmed live 2026-10-10: 682 postings, 82 in Ireland), so no JS or
# pagination is needed. Each listing points at locations by index into
# filters.locations; the Irish ones are the countryCode "IE" entries that
# have a parentLocationIndex ("Ireland", "Remote in Ireland", "Dublin
# HQ"). The parentless "Europe" region oddly also carries countryCode IE
# and must not count. A missing __NEXT_DATA__ raises rather than
# returning [], so a future layout change shows up as a failing scraper.
STRIPE_BASE = "https://stripe.com"
STRIPE_SEARCH = "https://stripe.com/careers/search"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def stripe(session) -> List[Job]:
    resp = fetch(session, STRIPE_SEARCH)
    match = _NEXT_DATA_RE.search(resp.content.decode("utf-8", errors="replace"))
    if not match:
        raise ValueError("Stripe careers page has no __NEXT_DATA__ job index (layout changed?)")
    index = json.loads(match.group(1))["props"]["pageProps"]["jobIndexData"]
    irish = {i for i, location in enumerate(index["filters"]["locations"])
             if location.get("countryCode") == "IE" and "parentLocationIndex" in location}
    jobs = []
    for listing in index["listings"]:
        if not irish & set(listing.get("locationIndices", [])):
            continue
        jobs.append(Job(
            "Stripe", listing["title"].strip(),
            f"{STRIPE_BASE}/careers/listing/{listing['slug']}/{listing['greenhouseId']}",
            STRIPE_SEARCH, sector="tech",
        ))
    return jobs


# JPMorganChase's careers site (jobs.jpmorganchase.com) runs on the exact
# same Oracle Recruiting Cloud (Fusion) platform pharma's alkermes()
# already uses in jobfinder/scrapers.py -- same hcmRestApi
# recruitingCEJobRequisitions "findReqs" finder pattern, just a new
# tenant host and site number. Confirmed live during design: 58 real
# Ireland postings via the LOCATIONS facet. Like Alkermes, the job
# detail page (hcmUI/CandidateExperience) is a client-rendered SPA shell
# with no server-side description -- see fetch_jpmorganchase_description
# in jobfinder/enrichment.py for how the listing API's own short
# description field is reused instead.
JPMORGANCHASE_API = "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
JPMORGANCHASE_JOB_BASE = "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job"
JPMORGANCHASE_PORTAL = "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs"
JPMORGANCHASE_IRELAND_FACET = "300000000289351"


def jpmorganchase(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 25
    while True:
        resp = fetch(session, JPMORGANCHASE_API, params={
            "onlyData": "true",
            "expand": "requisitionList",
            "finder": (
                "findReqs;siteNumber=CX_1001,facetsList=LOCATIONS,"
                f"limit={limit},offset={offset},"
                f"selectedLocationsFacet={JPMORGANCHASE_IRELAND_FACET}"
            ),
        })
        item = resp.json()["items"][0]
        total = item.get("TotalJobsCount", 0)
        reqs = item.get("requisitionList") or []
        for req in reqs:
            title = (req.get("Title") or "").strip()
            if title:
                jobs.append(Job(
                    "JPMorganChase", title,
                    f"{JPMORGANCHASE_JOB_BASE}/{req['Id']}", JPMORGANCHASE_PORTAL,
                    sector="tech",
                ))
        offset += len(reqs)
        if not reqs or offset >= total:
            break
    return jobs


# Salesforce's careers site runs on Workday, the same platform as
# mastercard()/accenture()/intel() above -- confirmed live during
# design: 116 real Ireland postings. One real wrinkle: this tenant's
# Ireland facet *parameter name* is a long custom string
# ("CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended"),
# not the simple "locationCountry" key Mastercard/Accenture/Intel use --
# discovered by requesting with empty appliedFacets and reading the
# `facets` array the API returns, which lists every available facet
# parameter alongside its values. The facet *value* GUID for Ireland is
# still the same shared, platform-wide one used elsewhere
# ("04a05835925f45b3a59406a2a6b72c8a").
SALESFORCE_API = "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs"
SALESFORCE_BASE = "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site"
SALESFORCE_FACETS = {
    "CF_-_REC_-_LRV_-_Job_Posting_Anchor_-_Country_from_Job_Posting_Location_Extended": [
        "04a05835925f45b3a59406a2a6b72c8a"
    ]
}


def salesforce(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, SALESFORCE_API, method="post", json={
            "appliedFacets": SALESFORCE_FACETS, "limit": limit, "offset": offset, "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            title = posting.get("title", "")
            jobs.append(Job(
                "Salesforce", title,
                SALESFORCE_BASE + posting.get("externalPath", ""), SALESFORCE_BASE,
                sector="tech",
            ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Infosys's careers page (by 2026-10) renders its results in the browser
# with Algolia InstantSearch, so the server HTML no longer carries the
# a.job cards the previous scraper read -- it silently returned zero.
# This queries the same Algolia index the page does, with the public
# search-only app ID and key its own script hands to algoliasearch()
# (assets/infosys/merged/js/...). The page's ?location= parameter maps to
# the `country` facet. Confirmed live 2026-10-10: 1,258 postings across 31
# countries and none in Ireland at the time, so an empty result here is
# genuine, not a layout change. redirect_url keeps the job-page format the
# old scraper stored, so existing job keys carry over. Note: the detail
# page only ever exposes an ellipsis-truncated description via static
# HTTP -- same class of dead end as Allianz Partners -- so Infosys is
# deliberately NOT added to ENRICHMENT_COMPANIES (see enrichment.py).
INFOSYS_SEARCH = "https://digitalcareers.infosys.com/infosys/global-careers?location=Ireland"
INFOSYS_ALGOLIA_URL = "https://UM59DWRPA1-dsn.algolia.net/1/indexes/production_Infosys_jobs/query"
INFOSYS_ALGOLIA_HEADERS = {
    "X-Algolia-Application-Id": "UM59DWRPA1",
    "X-Algolia-API-Key": "c8bffc42453b5122fd7e0aeb42761027",  # public search-only key from the page
}


def infosys(session) -> List[Job]:
    jobs = []
    page = 0
    while True:
        params = urlencode({"query": "", "hitsPerPage": 100, "page": page,
                            "facetFilters": json.dumps([["country:Ireland"]])})
        resp = fetch(session, INFOSYS_ALGOLIA_URL, method="post",
                     headers=INFOSYS_ALGOLIA_HEADERS, json={"params": params})
        data = resp.json()
        for hit in data.get("hits", []):
            url = hit.get("redirect_url")
            url = url[0] if isinstance(url, list) and url else url
            if not url:
                continue
            jobs.append(Job("Infosys", hit.get("title", "").strip(), url, INFOSYS_SEARCH, sector="tech"))
        page += 1
        if page >= data.get("nbPages", 0):
            break
    return jobs


TECH_SCRAPERS = OrderedDict([
    ("Google", google),
    ("Microsoft", microsoft),
    ("AIB", aib),
    ("Mastercard", mastercard),
    ("Accenture", accenture),
    ("Intel", intel),
    ("Citibank", citibank),
    ("Allianz Partners", allianz_partners),
    ("EY", ey),
    ("Amazon", amazon),
    ("AWS", aws),
    ("Stripe", stripe),
    ("JPMorganChase", jpmorganchase),
    ("Salesforce", salesforce),
    ("Infosys", infosys),
])
