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
# (canonical name, category, [match keywords]). Keywords are matched via
# word-boundary-anchored regex (see _compile_keyword) rather than naive
# substring matching, to avoid partial-word false positives on short tokens
# (e.g. bare "sap" matching inside "ASAP") while still matching keywords
# that are immediately followed by punctuation (e.g. "GMP," or "(GMP)").
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


def _compile_keyword(keyword: str) -> re.Pattern:
    """Compile a keyword string into a case-insensitive matching regex.

    Single-token keywords (no internal whitespace, e.g. "sap", "gmp",
    "excel") get \\b word-boundary anchors on whichever side(s) end in an
    alphanumeric character. That blocks partial-word false positives like
    bare "sap" matching inside "ASAP" or "excel" matching inside
    "excellent", while still matching short tokens immediately followed by
    punctuation, e.g. "GMP," or "(GMP)" (a bare trailing \\b after a
    non-alnum char like the "." in "sr." would never match, since neither
    side of that position is a word character — so we only add \\b where
    the keyword's own edge is alphanumeric).

    Multi-word phrases (e.g. "good manufacturing practice") are matched as
    a plain substring with no boundary anchoring: they're not vulnerable to
    this class of false positive, and anchoring the trailing edge would
    break legitimate plural/inflected matches (e.g. "Good Manufacturing
    Practices" should still match the "practice" phrase).
    """
    stripped = keyword.strip()
    if " " in stripped:
        return re.compile(re.escape(stripped), re.IGNORECASE)
    prefix = r"\b" if stripped[:1].isalnum() else ""
    suffix = r"\b" if stripped[-1:].isalnum() else ""
    return re.compile(prefix + re.escape(stripped) + suffix, re.IGNORECASE)


_SKILL_PATTERNS: List[Tuple[str, str, List[re.Pattern]]] = [
    (name, category, [_compile_keyword(kw) for kw in keywords])
    for name, category, keywords in SKILL_KEYWORDS
]


def extract_skills(description: str) -> List[Tuple[str, str]]:
    matched = []
    for name, category, patterns in _SKILL_PATTERNS:
        if any(p.search(description) for p in patterns):
            matched.append((name, category))
    return matched


# Order matters: most senior tier that matches wins.
SENIORITY_TIERS: List[Tuple[str, List[str]]] = [
    ("Director", ["director", "head of"]),
    ("Lead", ["lead", "principal"]),
    ("Senior", ["senior", "sr."]),
    ("Junior", ["junior", "graduate programme", "entry level", "intern"]),
]

_SENIORITY_PATTERNS: List[Tuple[str, List[re.Pattern]]] = [
    (tier, [_compile_keyword(kw) for kw in keywords])
    for tier, keywords in SENIORITY_TIERS
]


def extract_seniority(title: str) -> Optional[str]:
    for tier, patterns in _SENIORITY_PATTERNS:
        if any(p.search(title) for p in patterns):
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


# Pilot scope: this pipeline is being piloted on these two companies only
# (design spec §7: "pilot on 3-5 companies... before wider rollout").
# Several other companies' detail pages are known to 403 or serve an empty
# JS shell (Astellas, Amgen, APC, Vle Therapeutics, J&J confirmed during
# planning). If run() weren't scoped, enriching those jobs would write a
# permanent job_details row with enrichment_failed=1 — and since
# find_unenriched_jobs excludes any job with an existing job_details row,
# those jobs would never be retried, even after a future rollout adds a
# working fetcher for that company.
#
# Removing this list (or passing companies=None to find_unenriched_jobs) is
# the full-rollout step, to be done as its own separate change once more
# companies have working detail-page fetchers.
PILOT_COMPANIES = ["Abbvie", "BMS"]


def run(conn, session, now: str) -> EnrichmentResult:
    # Local import, not module-level: storage.py never imports enrichment.py,
    # but keeping this import inside run() keeps enrichment.py's module-level
    # import graph independent of storage.py, so the two can be reasoned
    # about — and unit-tested — in isolation.
    from jobfinder import storage

    result = EnrichmentResult()
    for job in storage.find_unenriched_jobs(conn, companies=PILOT_COMPANIES):
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
            try:
                storage.save_enrichment(conn, job["id"], "", None, [], now, failed=True)
            except Exception as recovery_exc:  # even recording the failure must not abort the batch
                log.error(
                    "Failed to record enrichment failure for %s (%s): %s",
                    job["company"], job["url"], recovery_exc,
                )
            result.failed += 1
    return result
