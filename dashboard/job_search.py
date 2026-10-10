"""Jobs page search: filter the job records, count every sidebar choice and
page the results. Pure Python over analytics.JobRecord lists -- no SQL, no
Flask -- so the rules in the dashboard spec's Jobs page section are tested
directly (tests/test_job_search.py)."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

from jobfinder.analytics import SENIORITY_LEVELS, JobRecord

PAGE_SIZE = 50
SECTORS = [("pharma", "Pharma"), ("tech", "Tech")]
WORK_MODES = [("onsite", "Onsite"), ("hybrid", "Hybrid"), ("remote", "Remote")]
CONTRACTS = [("permanent", "Permanent"), ("fixed_term", "Fixed-term"), ("contract", "Contract"),
             ("internship", "Internship")]
YEARS = [(2, "Up to 2 years"), (5, "Up to 5 years"), (8, "Up to 8 years")]
PERIODS = {"year": "a year", "month": "a month", "day": "a day", "hour": "an hour"}
# Groups built from Claude's reading: choosing any of them hides jobs Claude hasn't read.
CLAUDE_GROUPS = ("family", "seniority", "years", "mode", "contract")


@dataclass(frozen=True)
class Filters:
    sector: str = ""
    company: str = ""
    q: str = ""
    family: Tuple[str, ...] = ()
    seniority: Tuple[str, ...] = ()
    years: Optional[int] = None
    mode: Tuple[str, ...] = ()
    contract: Tuple[str, ...] = ()
    include_closed: bool = False
    page: int = 1

    @classmethod
    def from_args(cls, args) -> "Filters":
        """From the query string (a MultiDict). Unknown values are dropped,
        never an error; ?skill= (the old description search) is read as q
        when q is empty, so old bookmarks keep working."""
        def many(name, allowed):
            return tuple(v for v in dict.fromkeys(args.getlist(name)) if v in allowed)

        years = args.get("years", "")
        page = args.get("page", "1")
        return cls(
            sector=args.get("sector", "") if args.get("sector") in dict(SECTORS) else "",
            company=args.get("company", "").strip(),
            q=(args.get("q", "") or args.get("skill", "")).strip(),
            family=tuple(v for v in dict.fromkeys(args.getlist("family")) if v),
            seniority=many("seniority", SENIORITY_LEVELS),
            years=int(years) if years in {str(n) for n, _ in YEARS} else None,
            mode=many("mode", dict(WORK_MODES)),
            contract=many("contract", dict(CONTRACTS)),
            include_closed=args.get("all") == "1",
            page=int(page) if page.isdigit() and int(page) > 0 else 1,
        )

    @property
    def active_count(self) -> int:
        """How many choices narrow the list -- the "Filters (n)" label."""
        return (len(self.family) + len(self.seniority) + len(self.mode) + len(self.contract)
                + sum(1 for v in (self.sector, self.company, self.q, self.years) if v))

    def claude_used(self, skip: str = "") -> bool:
        return any(getattr(self, g) not in ((), None) for g in CLAUDE_GROUPS if g != skip)

    def query(self, **changes) -> str:
        """This search's query string with `changes` applied (page links)."""
        f = replace(self, **changes)
        pairs = [("sector", f.sector), ("company", f.company), ("q", f.q)]
        pairs += [("family", v) for v in f.family] + [("seniority", v) for v in f.seniority]
        pairs += [("years", f.years)] if f.years is not None else []
        pairs += [("mode", v) for v in f.mode] + [("contract", v) for v in f.contract]
        pairs += [("all", 1)] if f.include_closed else []
        pairs += [("page", f.page)] if f.page > 1 else []
        return urlencode([(k, v) for k, v in pairs if v not in ("", None)])


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    count: int
    selected: bool


@dataclass(frozen=True)
class SearchResult:
    filters: Filters
    cards: List[JobRecord]
    total: int
    page: int
    pages: int
    facets: Dict[str, List[Choice]]
    companies: List[Choice]


def _level(r: JobRecord) -> str:
    return r.seniority or "Not stated"


def _text_match(r: JobRecord, q: str) -> bool:
    q = q.casefold()
    return q in r.title.casefold() or any(q in s.casefold() for s in r.skills)


def _matches(r: JobRecord, f: Filters, skip: str = "") -> bool:
    """Does the job pass every filter except group `skip`? Skipping a group
    gives that group's own counts (disjunctive faceting)."""
    if skip != "sector" and f.sector and r.sector != f.sector:
        return False
    if not f.include_closed and not r.is_active:
        return False
    if skip != "company" and f.company and r.company != f.company:
        return False
    if f.q and not _text_match(r, f.q):
        return False
    if f.claude_used(skip) and not r.read_by_claude:
        return False
    if skip != "family" and f.family and r.role_family not in f.family:
        return False
    if skip != "seniority" and f.seniority and _level(r) not in f.seniority:
        return False
    if skip != "years" and f.years is not None and r.min_years is not None and r.min_years > f.years:
        return False
    if skip != "mode" and f.mode and r.work_mode not in f.mode:
        return False
    if skip != "contract" and f.contract and r.contract_type not in f.contract:
        return False
    return True


def _choices(records, f: Filters, group: str, options, value_of) -> List[Choice]:
    """A Claude group: each option's count applies every other group's
    choices, over jobs Claude has read. Empty options are hidden unless chosen."""
    counts = Counter(value_of(r) for r in records if _matches(r, f, skip=group) and r.read_by_claude)
    chosen = set(getattr(f, group))
    return [Choice(v, label, counts.get(v, 0), v in chosen) for v, label in options
            if counts.get(v, 0) or v in chosen]


def _family_choices(records, f: Filters) -> List[Choice]:
    counts = Counter(r.role_family for r in records
                     if _matches(r, f, skip="family") and r.read_by_claude and r.role_family)
    ordered = [v for v, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    ordered += [v for v in f.family if v not in counts]
    return [Choice(v, v, counts.get(v, 0), v in f.family) for v in ordered]


def _years_choices(records, f: Filters) -> List[Choice]:
    pool = [r for r in records if _matches(r, f, skip="years")]
    read = [r for r in pool if r.read_by_claude]
    choices = [Choice("", "Any", len(pool), f.years is None)]
    for n, label in YEARS:
        count = sum(1 for r in read if r.min_years is None or r.min_years <= n)
        choices.append(Choice(str(n), label, count, f.years == n))
    return choices


def _sector_choices(records, f: Filters) -> List[Choice]:
    counts = Counter(r.sector for r in records if _matches(r, f, skip="sector"))
    return ([Choice("", "All", sum(counts.values()), not f.sector)]
            + [Choice(v, label, counts.get(v, 0), f.sector == v) for v, label in SECTORS])


def _company_choices(records, f: Filters) -> List[Choice]:
    counts = Counter(r.company for r in records if _matches(r, f, skip="company"))
    names = sorted(set(counts) | ({f.company} if f.company else set()))
    return [Choice(c, c, counts.get(c, 0), c == f.company) for c in names]


def search(records: List[JobRecord], filters: Filters) -> SearchResult:
    known = {r.role_family for r in records if r.role_family}
    f = replace(filters, family=tuple(v for v in filters.family if v in known))
    matches = [r for r in records if _matches(r, f)]
    pages = max(1, math.ceil(len(matches) / PAGE_SIZE))
    f = replace(f, page=min(f.page, pages))
    start = (f.page - 1) * PAGE_SIZE
    facets = {
        "sector": _sector_choices(records, f),
        "family": _family_choices(records, f),
        "seniority": _choices(records, f, "seniority", [(v, v) for v in SENIORITY_LEVELS], _level),
        "years": _years_choices(records, f),
        "mode": _choices(records, f, "mode", WORK_MODES, lambda r: r.work_mode),
        "contract": _choices(records, f, "contract", CONTRACTS, lambda r: r.contract_type),
    }
    return SearchResult(f, matches[start:start + PAGE_SIZE], len(matches), f.page, pages, facets,
                        _company_choices(records, f))


def salary_text(r: JobRecord) -> Optional[str]:
    """'€90–92k a year'; other currencies keep their code ('USD 191–300k a
    year'), since they are often a US range on an Irish posting. None when
    the posting states no pay."""
    values = [v for v in (r.salary_min, r.salary_max) if v is not None]
    if not values:
        return None
    low, high = min(values), max(values)
    if low >= 1000:
        amount = f"{low / 1000:.0f}k" if low == high else f"{low / 1000:.0f}–{high / 1000:.0f}k"
    else:
        amount = f"{low:,.0f}" if low == high else f"{low:,.0f}–{high:,.0f}"
    currency = (r.salary_currency or "").upper()
    prefix = "€" if currency == "EUR" else (f"{currency} " if currency else "")
    period = PERIODS.get(r.salary_period or "")
    return f"{prefix}{amount} {period}" if period else f"{prefix}{amount}"


def card_facts(r: JobRecord) -> List[str]:
    """The stated facts for a card's one-line summary, in reading order."""
    facts = []
    if r.seniority and r.seniority != "Not stated":
        facts.append(r.seniority)
    if r.min_years is not None:
        facts.append(f"{r.min_years}+ yrs")
    if r.work_mode in dict(WORK_MODES):
        facts.append(dict(WORK_MODES)[r.work_mode])
    if r.contract_type in dict(CONTRACTS):
        facts.append(dict(CONTRACTS)[r.contract_type])
    salary = salary_text(r)
    if salary:
        facts.append(salary)
    return facts
