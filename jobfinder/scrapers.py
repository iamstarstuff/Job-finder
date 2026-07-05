from __future__ import annotations

import logging
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


def amgen(session) -> List[Job]:
    jobs = []
    url = URLS["Amgen"]
    while url:
        soup = _soup(fetch(session, url))
        for h4 in soup.find_all("h4"):
            a = h4.find("a")
            if a is None:
                continue
            jobs.append(Job(
                "Amgen", h4.text.strip(),
                urljoin("https://www.amgen.jobs", a["href"]),
                URLS["Amgen"],
            ))
        url = _follow_next(soup, url)
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


BMS_API = "https://jobs.bms.com/api/apply/v2/jobs"
BMS_PORTAL = "https://jobs.bms.com/careers?location=ireland"


def bms(session) -> List[Job]:
    jobs = []
    start = 0
    num = 20
    while True:
        resp = fetch(session, BMS_API, params={
            "domain": "bms.com", "location": "Ireland",
            "start": start, "num": num,
        })
        data = resp.json()
        positions = data.get("positions", [])
        for pos in positions:
            jobs.append(Job(
                "BMS", pos.get("name", "").strip(),
                pos.get("canonicalPositionUrl", ""),
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
            jobs.append(Job("MSD", item.get("title", "").strip(), url, MSD_PORTAL))
        offset += len(batch)
        if not batch or offset >= payload.get("totalHits", 0):
            break
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
    # BMS excluded: Eightfold API returns 401 without browser session; see task-8 report
    ("MSD", msd),
])
