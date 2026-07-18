from __future__ import annotations

import json
import re
from typing import List

from jobfinder.http_client import fetch
from jobfinder.models import Job

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
    jobs = []
    page = 1
    seen_first_ids = set()
    while True:
        resp = fetch(session, f"{GOOGLE_SEARCH}{page}")
        entries = _extract_google_data_chunk(resp.content.decode("utf-8"))
        if not entries:
            break
        first_id = entries[0][0]
        if first_id in seen_first_ids:
            break  # server clamped to an already-seen page -- no more real results
        seen_first_ids.add(first_id)
        for entry in entries:
            job_id, title, apply_url = entry[0], entry[1], entry[2]
            if matches_target_role(title):
                jobs.append(Job("Google", title, apply_url, GOOGLE_PORTAL, sector="tech"))
        page += 1
        if page > 500:  # safety cap -- should never trigger in practice
            raise RuntimeError("Google pagination exceeded safety cap of 500 pages")
    return jobs
