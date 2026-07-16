from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

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
