from __future__ import annotations

import logging
import re
import unicodedata
from collections import OrderedDict
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from jobfinder.http_client import fetch
from jobfinder.models import Job

URLS = {
    "APC": "https://approcess.com/careers",
    "Abbvie": "https://careers.abbvie.com/en/jobs?q=&options=&page=1&la=53.3498053&lo=-6.2603097&ln=Dublin,%20Ireland&lr=100",
    "Astrazeneca": "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2",
    "Takeda": "https://jobs.takeda.com/search-jobs/Ireland/1113/2/2963597/53/-8/50/2",
    "Amgen": "https://www.amgen.jobs/irl/jobs/",
    "Vle therapeutics": "https://www.vletherapeutics.com/careers",
    "Astellas": "https://astellas.avature.net/en_GB/careers/SearchJobs/?1329=%5B180801%5D&1329_format=1348&listFilterMode=1&jobOffset=",
    "Jazz Pharmaceuticals": "https://careers.jazzpharma.com/jobs/ie/",
}

log = logging.getLogger(__name__)


def _soup(response) -> BeautifulSoup:
    return BeautifulSoup(response.content, "lxml")


def _follow_next(soup, current_url):
    """Return absolute URL of a 'next page' link, or None."""
    nxt = soup.find("a", class_="next") or soup.find("a", rel="next")
    if nxt and nxt.get("href"):
        return urljoin(current_url, nxt["href"])
    return None


def apc(session) -> List[Job]:
    jobs = []
    url = URLS["APC"]
    while url:
        soup = _soup(fetch(session, url))
        table = soup.find("table")
        for row in table.find_all("tr")[1:]:
            title = row.find("td", class_="title title--quaternary").text.strip()
            closing = row.find("td", class_="title title--senary").text.strip()
            link = urljoin(url, row.find("a")["href"])
            jobs.append(Job("APC", title, link, URLS["APC"], closing))
        url = _follow_next(soup, url)
    return jobs


def abbvie(session) -> List[Job]:
    soup = _soup(fetch(session, URLS["Abbvie"]))
    jobs = []
    for tile in soup.find_all("a", class_="attrax-vacancy-tile__title"):
        jobs.append(Job(
            "Abbvie",
            tile.get_text(strip=True),
            urljoin("https://careers.abbvie.com", tile["href"]),
            URLS["Abbvie"],
        ))
    return jobs


def astrazeneca(session) -> List[Job]:
    jobs = []
    page = 1
    while True:
        soup = _soup(fetch(session, f"{URLS['Astrazeneca']}/{page}"))
        tiles = soup.find_all("a", class_="search-results-link")
        if not tiles:
            break
        for tile in tiles:
            title = tile.text.strip().split("\n")[0]
            jobs.append(Job(
                "Astrazeneca", title,
                urljoin("https://careers.astrazeneca.com/", tile["href"]),
                URLS["Astrazeneca"],
            ))
        page += 1
    return jobs


def takeda(session) -> List[Job]:
    soup = _soup(fetch(session, URLS["Takeda"]))
    jobs = []
    for link in soup.find_all("a", {"data-job-id": True}):
        h2 = link.find("h2", class_="title")
        if h2 is None:
            continue
        jobs.append(Job(
            "Takeda", h2.text.strip(),
            urljoin("https://jobs.takeda.com/", link["href"]),
            URLS["Takeda"],
        ))
    return jobs


AMGEN_API = "https://prod-search-api.jobsyn.org/api/v1/solr/search"
AMGEN_BASE = "https://www.amgen.jobs"
# The site's own Nuxt bundle builds job urls as
# `/${slugify(location_exact)}/${title_slug}/${guid}/job/`; slugify normalizes
# to NFD, strips diacritics/quotes, then joins \w+ chunks with "-".


def _amgen_slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    stripped = re.sub(r"[\"’+:/]", "", stripped)
    words = re.findall(r"\w+", stripped)
    return "-".join(w.lower() for w in words)


def amgen(session) -> List[Job]:
    jobs = []
    page = 1
    while True:
        resp = fetch(
            session, AMGEN_API,
            params={"location": "Ireland", "page": page},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Origin": "www.amgen.jobs",
            },
        )
        data = resp.json()
        batch = data.get("jobs", [])
        if not batch:
            break
        for item in batch:
            title = item.get("title_exact", "").strip()
            if not title:
                continue
            path = "/{}/{}/{}/job/".format(
                _amgen_slugify(item.get("location_exact", "")),
                item.get("title_slug", ""),
                item.get("guid", ""),
            )
            jobs.append(Job("Amgen", title, urljoin(AMGEN_BASE, path), URLS["Amgen"]))
        pagination = data.get("pagination", {})
        total = pagination.get("total", 0)
        if len(jobs) >= total or not pagination.get("has_more_pages", False):
            break
        page += 1
    return jobs


def vle(session) -> List[Job]:
    soup = _soup(fetch(session, URLS["Vle therapeutics"]))
    jobs = []
    for block in soup.find_all("div", class_="table-content"):
        closing = block.find("p", class_="close-date")
        jobs.append(Job(
            "Vle therapeutics",
            block.find("p", class_="job-description").text.strip(),
            urljoin(URLS["Vle therapeutics"], block.find("a", class_="careers-link")["href"]),
            URLS["Vle therapeutics"],
            closing.text.strip() if closing else None,
        ))
    return jobs


def astellas(session) -> List[Job]:
    jobs = []
    offset = 0
    while True:
        url = f"{URLS['Astellas']}{offset}"
        soup = _soup(fetch(session, url))
        tiles = soup.find_all("h3", class_="article__header__text__title")
        if not tiles:
            break
        for tile in tiles:
            jobs.append(Job("Astellas", tile.text.strip(), urljoin(url, tile.find("a")["href"]), url))
        offset += 10
    return jobs


PFIZER_API = "https://pfizer.wd1.myworkdayjobs.com/wday/cxs/pfizer/PfizerCareers/jobs"
PFIZER_BASE = "https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers"
# Facet GUID for Ireland, taken from the original careers URL
PFIZER_FACETS = {"Location_Country": ["04a05835925f45b3a59406a2a6b72c8a"]}


def pfizer(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, PFIZER_API, method="post", json={
            "appliedFacets": PFIZER_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            if not posting.get("title"):
                continue
            jobs.append(Job(
                "Pfizer", posting["title"],
                PFIZER_BASE + posting.get("externalPath", ""),
                PFIZER_BASE,
            ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Eightfold "pcsx" search API — the /api/apply/v2/jobs path 403s, but this
# endpoint (the one the careers SPA itself calls) works anonymously.
BMS_API = "https://jobs.bms.com/api/pcsx/search"
BMS_BASE = "https://jobs.bms.com"
BMS_PORTAL = "https://jobs.bms.com/careers?domain=bms.com&location=Ireland"


def bms(session) -> List[Job]:
    jobs = []
    start = 0
    while True:
        resp = fetch(session, BMS_API, params={
            "domain": "bms.com", "query": "", "location": "Ireland",
            "start": start, "sort_by": "distance", "filter_include_remote": 1,
        })
        data = resp.json().get("data", {})
        positions = data.get("positions", [])
        for pos in positions:
            jobs.append(Job(
                "BMS", pos.get("name", "").strip(),
                urljoin(BMS_BASE, pos.get("positionUrl", "")),
                BMS_PORTAL,
            ))
        start += len(positions)
        if not positions or start >= data.get("count", 0):
            break
    return jobs


MSD_API = "https://jobs.msd.com/widgets"
MSD_PORTAL = "https://jobs.msd.com/gb/en/ireland-job-search"


def _msd_payload(offset: int, size: int) -> dict:
    return {
        "lang": "en", "deviceType": "desktop", "country": "gb",
        "pageName": "search-results", "ddoKey": "refineSearch",
        "sortBy": "", "subsearch": "", "from": offset, "jobs": True,
        "counts": True, "all_fields": ["category", "country", "state", "city", "type"],
        "size": size, "clearAll": False, "jdsource": "facets",
        "isSliderEnable": False, "pageId": "page10", "siteType": "external",
        "keywords": "", "global": True,
        "selected_fields": {"country": ["Ireland"]}, "locationData": {},
    }


def msd(session) -> List[Job]:
    jobs = []
    offset = 0
    size = 20
    while True:
        resp = fetch(session, MSD_API, method="post", json=_msd_payload(offset, size))
        payload = resp.json().get("refineSearch", {})
        batch = payload.get("data", {}).get("jobs", [])
        for item in batch:
            url = item.get("applyUrl") or item.get("jobUrl") or ""
            # applyUrl points at the application form; link the listing page instead
            if url.endswith("/apply"):
                url = url[: -len("/apply")]
            jobs.append(Job("MSD", item.get("title", "").strip(), url, MSD_PORTAL))
        offset += len(batch)
        if not batch or offset >= payload.get("totalHits", 0):
            break
    return jobs


GILEAD_API = "https://gilead.wd1.myworkdayjobs.com/wday/cxs/gilead/gileadcareers/jobs"
GILEAD_BASE = "https://gilead.wd1.myworkdayjobs.com/en-US/gileadcareers"
# This tenant has no country-level facet (unlike Pfizer's Location_Country
# GUID) — its "locations" facet only exposes individual city entries.
# Verified live: "Ireland - Cork" is the only Irish location.
GILEAD_FACETS = {"locations": ["173342972c12019c9d3b6073b0740a39"]}


def gilead(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, GILEAD_API, method="post", json={
            "appliedFacets": GILEAD_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            if not posting.get("title"):
                continue
            jobs.append(Job(
                "Gilead", posting["title"],
                GILEAD_BASE + posting.get("externalPath", ""),
                GILEAD_BASE,
            ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Jazz Pharmaceuticals' careers site is NOT Workday, despite the tenant
# domains suggested by the brief (jazzpharma.wd5 / jazz.wd1 / vhr-jazz.wd1
# all either 404/500 or reject the cxs jobs payload with HTTP 422 — verified
# live). Their real job search lives on careers.jazzpharma.com, a
# server-rendered site with the same "?page_jobs=N" / "a.next" pagination
# convention used elsewhere in this file (see _follow_next).


def jazz(session) -> List[Job]:
    jobs = []
    url = URLS["Jazz Pharmaceuticals"]
    while url:
        soup = _soup(fetch(session, url))
        results = soup.find("ul", class_="results-content")
        tiles = results.find_all("li", recursive=False) if results else []
        for tile in tiles:
            h3 = tile.find("h3")
            link = tile.find("a")
            if not h3 or not link:
                continue
            jobs.append(Job(
                "Jazz Pharmaceuticals", h3.text.strip(),
                urljoin(url, link["href"]),
                URLS["Jazz Pharmaceuticals"],
            ))
        url = _follow_next(soup, url)
    return jobs


THERMO_API = "https://jobs.thermofisher.com/widgets"
THERMO_PORTAL = "https://jobs.thermofisher.com/global/en/search-results?qsr=Ireland"


def _thermo_payload(offset: int, size: int) -> dict:
    return {
        "lang": "en", "deviceType": "desktop", "country": "us",
        "pageName": "search-results", "ddoKey": "refineSearch",
        "sortBy": "", "subsearch": "", "from": offset, "jobs": True,
        "counts": True, "all_fields": ["category", "country", "state", "city", "type"],
        "size": size, "clearAll": False, "jdsource": "facets",
        "isSliderEnable": False, "pageId": "page10", "siteType": "external",
        "keywords": "", "global": True,
        "selected_fields": {"country": ["Ireland"]}, "locationData": {},
    }


def thermo_fisher(session) -> List[Job]:
    jobs = []
    offset = 0
    size = 20
    while True:
        resp = fetch(session, THERMO_API, method="post", json=_thermo_payload(offset, size))
        payload = resp.json().get("refineSearch", {})
        batch = payload.get("data", {}).get("jobs", [])
        for item in batch:
            url = item.get("applyUrl") or item.get("jobUrl") or ""
            # applyUrl points at the application form; link the listing page instead
            if url.endswith("/apply"):
                url = url[: -len("/apply")]
            jobs.append(Job("Thermo Fisher", item.get("title", "").strip(), url, THERMO_PORTAL))
        offset += len(batch)
        if not batch or offset >= payload.get("totalHits", 0):
            break
    return jobs


# Johnson & Johnson's careers.jnj.com is NOT the Phenom /widgets JSON API the
# brief expected -- verified live, the page ships server-rendered job tiles
# (no refineSearch/ddoKey markers anywhere in the HTML). It's a GET-param
# filtered search (?country=Ireland) with the same "next page link" pagination
# convention as jazz(), so it reuses _soup/_follow_next.
JNJ_URL = "https://www.careers.jnj.com/en/jobs/?country=Ireland"
JNJ_BASE = "https://www.careers.jnj.com"


def johnson_and_johnson(session) -> List[Job]:
    jobs = []
    url = JNJ_URL
    while url:
        soup = _soup(fetch(session, url))
        results = soup.find("ul", id="js-job-search-results")
        tiles = results.find_all("li", class_="card-job") if results else []
        for tile in tiles:
            link = tile.find("a", class_="js-view-job")
            if not link:
                continue
            jobs.append(Job(
                "Johnson & Johnson", link.get_text(strip=True),
                urljoin(JNJ_BASE, link["href"]),
                JNJ_URL,
            ))
        url = _follow_next(soup, url)
    return jobs


REGENERON_API = "https://regeneron.wd1.myworkdayjobs.com/wday/cxs/regeneron/Careers/jobs"
REGENERON_BASE = "https://regeneron.wd1.myworkdayjobs.com/en-US/Careers"
# Regeneron has no country-level facet (like Gilead) -- its "locations" facet
# exposes individual city entries. Verified live: "Dublin" and "Limerick" are
# the Irish offices (a "Remote - Ireland" entry also exists but was excluded
# to avoid pulling in jobs based elsewhere that merely allow Irish remote
# work).
REGENERON_FACETS = {"locations": [
    "8fa87bf3f848012f5b685634fb005a03",  # Dublin
    "8fa87bf3f84801d96a745d34fb006a03",  # Limerick
]}


def regeneron(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, REGENERON_API, method="post", json={
            "appliedFacets": REGENERON_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            if not posting.get("title"):
                continue
            jobs.append(Job(
                "Regeneron", posting["title"],
                REGENERON_BASE + posting.get("externalPath", ""),
                REGENERON_BASE,
            ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# GSK's own guessed tenant (gsk.wd5.myworkdayjobs.com) is live but currently
# has zero Ireland postings -- verified via full-text search for "Cork" /
# "Dungarvan" / "Ireland" (all returned 0, or an unrelated Northern-Ireland
# match). GSK's Cork/Dungarvan manufacturing sites are actually posted on a
# separate Workday tenant, "gsknch" (same GSKCareers site name), which does
# have live Dungarvan postings -- verified live via the "location" facet
# ("Ireland - Dungarvan") and a full-text "Dungarvan" search (4 hits).
GSK_API = "https://gsknch.wd3.myworkdayjobs.com/wday/cxs/gsknch/GSKCareers/jobs"
GSK_BASE = "https://gsknch.wd3.myworkdayjobs.com/en-US/GSKCareers"
GSK_FACETS = {"location": ["03fe97f04c9a0198b3d87109a8571d6d"]}  # Ireland - Dungarvan


def gsk(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    while True:
        resp = fetch(session, GSK_API, method="post", json={
            "appliedFacets": GSK_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        })
        data = resp.json()
        postings = data.get("jobPostings", [])
        for posting in postings:
            if not posting.get("title"):
                continue
            jobs.append(Job(
                "GSK", posting["title"],
                GSK_BASE + posting.get("externalPath", ""),
                GSK_BASE,
            ))
        offset += len(postings)
        if not postings or offset >= data.get("total", 0):
            break
    return jobs


# Alkermes' careers.alkermes.com redirects to an Oracle Recruiting Cloud (Fusion
# HCM Candidate Experience) tenant, not any of the ATS patterns in the brief's
# discovery list -- verified live: the redirect target's <base> tag exposes
# data-apibaseurl="https://hbap.fa.us1.oraclecloud.com". Its REST API
# (hcmRestApi/resources/latest/recruitingCEJobRequisitions) is callable
# anonymously with no auth headers. The "LOCATIONS" facet's country-level
# entries were fetched once to find "Ireland" -> id 300000000191040
# (verified live: 2 hits, both Dublin).
ALKERMES_API = "https://hbap.fa.us1.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
ALKERMES_JOB_BASE = "https://hbap.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job"
ALKERMES_PORTAL = "https://careers.alkermes.com/"
ALKERMES_IRELAND_FACET = "300000000191040"


def alkermes(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 25
    while True:
        resp = fetch(session, ALKERMES_API, params={
            "onlyData": "true",
            "expand": "requisitionList",
            "finder": (
                "findReqs;siteNumber=CX_1,facetsList=LOCATIONS,"
                f"limit={limit},offset={offset},"
                f"selectedLocationsFacet={ALKERMES_IRELAND_FACET}"
            ),
        })
        item = resp.json()["items"][0]
        total = item.get("TotalJobsCount", 0)
        reqs = item.get("requisitionList") or []
        for req in reqs:
            title = (req.get("Title") or "").strip()
            if not title:
                continue
            jobs.append(Job(
                "Alkermes", title,
                f"{ALKERMES_JOB_BASE}/{req['Id']}",
                ALKERMES_PORTAL,
            ))
        offset += len(reqs)
        if not reqs or offset >= total:
            break
    return jobs


# Teva's www.tevapharm.com/careers/ redirects to the Eightfold-hosted
# www.careers.teva/careers -- same ATS family as bms(), but the "pcsx" search
# endpoint bms() uses 403s here ("PCSX is not enabled for this user", verified
# live). The underlying Eightfold widget itself calls /api/apply/v2/jobs
# (the endpoint that 403s for BMS) which works anonymously for this domain.
TEVA_API = "https://www.careers.teva/api/apply/v2/jobs"
TEVA_PORTAL = "https://www.careers.teva/careers?location=Ireland"


def teva(session) -> List[Job]:
    jobs = []
    start = 0
    while True:
        resp = fetch(session, TEVA_API, params={
            "domain": "tevapharm.com", "query": "", "location": "Ireland", "start": start,
        })
        data = resp.json()
        positions = data.get("positions", [])
        for pos in positions:
            title = (pos.get("name") or "").strip()
            if not title:
                continue
            jobs.append(Job(
                "Teva", title,
                pos.get("canonicalPositionUrl", ""),
                TEVA_PORTAL,
            ))
        start += len(positions)
        if not positions or start >= data.get("count", 0):
            break
    return jobs


# Viatris' www.viatris.ie/en-ie/careers links to a Workday tenant
# (viatris.wd5.myworkdayjobs.com/External) -- same pattern as pfizer()/
# gilead(). Unlike Pfizer, the appliedFacets key is "Country" not
# "Location_Country" (verified live: posting a "Location_Country" facet
# 400s; the tenant's own facets response names the field "Country"). The
# GUID in the site's own career-page link ("...?Country=04a058...") is
# confirmed live as Ireland (61 hits).
# This tenant's "total" field is only reliable on the *first* page --
# verified live, pages 2+ report total=0 (postings keep coming correctly)
# and paging past the true end wraps back around to page-1 results with
# total=61 again. So "total" is captured once from the first response and
# reused, rather than re-read (and trusted) on every page.
VIATRIS_API = "https://viatris.wd5.myworkdayjobs.com/wday/cxs/viatris/External/jobs"
VIATRIS_BASE = "https://viatris.wd5.myworkdayjobs.com/en-US/External"
VIATRIS_FACETS = {"Country": ["04a05835925f45b3a59406a2a6b72c8a"]}


def viatris(session) -> List[Job]:
    jobs = []
    offset = 0
    limit = 20
    total = None
    while True:
        resp = fetch(session, VIATRIS_API, method="post", json={
            "appliedFacets": VIATRIS_FACETS,
            "limit": limit,
            "offset": offset,
            "searchText": "",
        })
        data = resp.json()
        if total is None:
            total = data.get("total", 0)
        postings = data.get("jobPostings", [])
        for posting in postings:
            if not posting.get("title"):
                continue
            jobs.append(Job(
                "Viatris", posting["title"],
                VIATRIS_BASE + posting.get("externalPath", ""),
                VIATRIS_BASE,
            ))
        offset += len(postings)
        if not postings or offset >= total:
            break
    return jobs


# Grifols' www.grifols.com/en/careers links to jobsearch.grifols.com, a
# legacy SAP SuccessFactors "job2web" career site (server-rendered HTML
# table, same platform Leo Pharma uses below). /search/?locationsearch=
# filters by location text and is paginated via "startrow"; the results
# table degrades to an unrelated default list once startrow reaches the
# filtered total (verified live), so pagination must stop via the parsed
# total rather than looping on "any rows returned".
GRIFOLS_BASE = "https://jobsearch.grifols.com"
GRIFOLS_SEARCH = "https://jobsearch.grifols.com/search/?q=&locationsearch=Ireland&startrow="
GRIFOLS_PORTAL = "https://jobsearch.grifols.com/search/?q=&locationsearch=Ireland"


def grifols(session) -> List[Job]:
    jobs = []
    offset = 0
    total = None
    while total is None or offset < total:
        soup = _soup(fetch(session, f"{GRIFOLS_SEARCH}{offset}"))
        rows = soup.find_all("tr", class_="data-row")
        if not rows:
            break
        for row in rows:
            link = row.find("a", class_="jobTitle-link")
            if not link:
                continue
            jobs.append(Job(
                "Grifols", link.get_text(strip=True),
                urljoin(GRIFOLS_BASE, link["href"]),
                GRIFOLS_PORTAL,
            ))
        label = soup.find("span", class_="paginationLabel")
        bolds = label.find_all("b") if label else []
        total = int(bolds[-1].get_text(strip=True)) if bolds else len(rows)
        offset += len(rows)
    return jobs


# Leo Pharma's www.leo-pharma.com/your-career/jobs links to
# jobs.leo-pharma.com, the same SuccessFactors "job2web" platform as
# Grifols above (identical markup/pagination) -- reuses the same shape.
# locationsearch=Ireland/Dublin/Cork all return zero results, and a full
# scan of every live posting (5 pages / ~110 jobs, verified live) found no
# Ireland location at all. Registered anyway since the pattern itself
# works and will pick up a listing the moment Leo Pharma posts one.
LEO_BASE = "https://jobs.leo-pharma.com"
LEO_SEARCH = "https://jobs.leo-pharma.com/search/?q=&locationsearch=Ireland&startrow="
LEO_PORTAL = "https://jobs.leo-pharma.com/search/?q=&locationsearch=Ireland"


def leo_pharma(session) -> List[Job]:
    jobs = []
    offset = 0
    total = None
    while total is None or offset < total:
        soup = _soup(fetch(session, f"{LEO_SEARCH}{offset}"))
        rows = soup.find_all("tr", class_="data-row")
        if not rows:
            break
        for row in rows:
            link = row.find("a", class_="jobTitle-link")
            if not link:
                continue
            jobs.append(Job(
                "Leo Pharma", link.get_text(strip=True),
                urljoin(LEO_BASE, link["href"]),
                LEO_PORTAL,
            ))
        label = soup.find("span", class_="paginationLabel")
        bolds = label.find_all("b") if label else []
        total = int(bolds[-1].get_text(strip=True)) if bolds else len(rows)
        offset += len(rows)
    return jobs


# ICON plc's careers.iconplc.com is server-rendered Attrax (same platform as
# abbvie()), "powered by SmartRecruiters" per its own footer, but the
# geo-radius search abbvie() uses (la/lo/lr around Dublin's coordinates)
# returns zero results here -- verified live. ICON posts globally across 53
# countries with no Ireland entry in the default location-facet sidebar, so
# instead this uses the site's own keyword search (?q=Ireland), which does
# surface every Ireland posting -- but also non-Ireland noise: Northern
# Ireland postings and unrelated jobs whose descriptions merely mention
# "Ireland" (verified live, e.g. UK/Poland roles with no Ireland location).
# Every genuine Republic-of-Ireland listing's own URL slug contains
# "-in-ireland-" (e.g. ".../in-ireland-dublin-jid-..."), which Northern
# Ireland postings (".../northern-ireland-jid-...") do not -- so results are
# filtered on that slug marker rather than trusted keyword relevance.
ICON_BASE = "https://careers.iconplc.com"
ICON_SEARCH = "https://careers.iconplc.com/jobs?q=Ireland&page="
ICON_PORTAL = "https://careers.iconplc.com/jobs?q=Ireland"


def icon(session) -> List[Job]:
    jobs = []
    seen = set()
    page = 1
    while True:
        soup = _soup(fetch(session, f"{ICON_SEARCH}{page}"))
        tiles = soup.find_all("a", class_="attrax-vacancy-tile__title")
        if not tiles:
            break
        for tile in tiles:
            href = tile.get("href", "")
            if "-in-ireland-" not in href.lower():
                continue
            url = urljoin(ICON_BASE, href)
            if url in seen:
                continue
            seen.add(url)
            jobs.append(Job("ICON", tile.get_text(strip=True), url, ICON_PORTAL))
        page += 1
    return jobs


SCRAPERS = OrderedDict([
    ("APC", apc),
    ("Abbvie", abbvie),
    ("Astrazeneca", astrazeneca),
    ("Takeda", takeda),
    ("Amgen", amgen),
    ("Vle therapeutics", vle),
    ("Astellas", astellas),
    ("Pfizer", pfizer),
    ("BMS", bms),
    ("MSD", msd),
    ("Gilead", gilead),
    ("Jazz Pharmaceuticals", jazz),
    ("Thermo Fisher", thermo_fisher),
    ("Johnson & Johnson", johnson_and_johnson),
    ("Regeneron", regeneron),
    ("GSK", gsk),
    ("Alkermes", alkermes),
    ("Teva", teva),
    ("Viatris", viatris),
    ("Grifols", grifols),
    ("Leo Pharma", leo_pharma),
    ("ICON", icon),
])
