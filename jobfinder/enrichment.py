from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from jobfinder.http_client import fetch

log = logging.getLogger(__name__)

_LDJSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def extract_ldjson_description(html: str) -> Optional[str]:
    """Look for a schema.org JobPosting JSON-LD block and return its
    description as clean plain text (HTML tags stripped). Returns None if
    no such block is present, unparseable, or has no description — this
    is the common case for JS-rendered SPA detail pages."""
    for block in _LDJSON_RE.findall(html):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("@type") != "JobPosting":
            continue
        description = data.get("description")
        if not description:
            continue
        return BeautifulSoup(description, "lxml").get_text(separator=" ", strip=True)
    return None


# Order doesn't matter for skills (a job can match many), but each tuple is
# (canonical name, category, [substring match keywords], text pre/post-padded
# with a space before matching to avoid partial-word false positives on
# short tokens).
SKILL_KEYWORDS: List[Tuple[str, str, List[str]]] = [
    ("GMP", "Regulatory", ["good manufacturing practice", " gmp "]),
    ("SOP", "Regulatory", ["standard operating procedure"]),
    ("Six Sigma", "Methodology", ["six sigma"]),
    ("Lean Manufacturing", "Methodology", ["lean manufacturing"]),
    ("SAP", "Software", [" sap ", "sap"]),
    ("Trackwise", "Software", ["trackwise"]),
    ("Veeva Vault", "Software", ["veeva vault", "veeva"]),
    ("Maximo", "Software", ["maximo"]),
    ("Excel", "Software", ["microsoft excel", " excel "]),
    ("Python", "Software", ["python"]),
    ("SQL", "Software", [" sql "]),
    ("Validation", "Regulatory", ["process validation", "equipment validation"]),
]


def extract_skills(description: str) -> List[Tuple[str, str]]:
    lowered = f" {description.lower()} "
    matched = []
    for name, category, keywords in SKILL_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            matched.append((name, category))
    return matched


# Order matters: most senior tier that matches wins.
SENIORITY_TIERS: List[Tuple[str, List[str]]] = [
    ("Director", ["director", "head of"]),
    ("Lead", ["lead", "principal"]),
    ("Senior", ["senior", "sr."]),
    ("Junior", ["junior", "graduate programme", "entry level", "intern"]),
]


def extract_seniority(title: str) -> Optional[str]:
    lowered = f" {title.lower()} "
    for tier, keywords in SENIORITY_TIERS:
        if any(kw in lowered for kw in keywords):
            return tier
    return None


def fetch_description(session, url: str) -> Optional[str]:
    response = fetch(session, url)
    html = response.content.decode("utf-8", errors="replace")
    return extract_ldjson_description(html)


@dataclass
class EnrichmentResult:
    enriched: int = 0
    failed: int = 0


def run(conn, session, now: str) -> EnrichmentResult:
    # Local import, not module-level: storage.py never imports enrichment.py,
    # but keeping this import inside run() keeps enrichment.py's module-level
    # import graph independent of storage.py, so the two can be reasoned
    # about — and unit-tested — in isolation.
    from jobfinder import storage

    result = EnrichmentResult()
    for job in storage.find_unenriched_jobs(conn):
        try:
            description = fetch_description(session, job["url"])
            if description is None:
                storage.save_enrichment(conn, job["id"], "", None, [], now, failed=True)
                result.failed += 1
                log.warning("No JSON-LD description found for %s (%s)", job["company"], job["url"])
                continue
            seniority = extract_seniority(job["title"])
            skills = extract_skills(description)
            storage.save_enrichment(conn, job["id"], description, seniority, skills, now, failed=False)
            result.enriched += 1
        except Exception as exc:  # per-job isolation — one bad job must never stop the batch
            log.warning("Enrichment failed for %s (%s): %s", job["company"], job["url"], exc)
            storage.save_enrichment(conn, job["id"], "", None, [], now, failed=True)
            result.failed += 1
    return result
