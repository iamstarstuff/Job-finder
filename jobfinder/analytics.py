from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

# Order matters: first match wins.
CATEGORY_KEYWORDS = [
    ("Quality", ["qa", "qc", "quality", "validation", "compliance"]),
    ("Regulatory", ["regulatory", "pharmacovigilance", "medical affairs"]),
    ("R&D / Science", ["scientist", "research", "r&d", "laboratory", "biolog",
                       "chemist", "analytical"]),
    ("Engineering", ["engineer", "engineering", "maintenance", "automation",
                     "technician", "utilities"]),
    ("Manufacturing / Ops", ["manufacturing", "production", "operator",
                             "operations", "warehouse", "supply chain",
                             "logistics", "packaging"]),
    ("IT / Digital", [" it ", "digital", "data", "software", "system"]),
    ("Commercial", ["sales", "marketing", "commercial", " account ",
                    "business development", "product specialist"]),
    ("HR / Finance / Admin", [" hr ", "human resources", "finance", "accountant",
                              "administrat", "payroll", "legal"]),
]


def categorize(title: str) -> str:
    lowered = f" {title.lower()} "
    for category, keywords in CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return category
    return "Other"


def week_start(iso_ts: str) -> str:
    """Monday (YYYY-MM-DD) of the ISO week containing the timestamp."""
    d = datetime.fromisoformat(iso_ts).date()
    return (d - timedelta(days=d.weekday())).isoformat()


def week_label(week: str) -> str:
    """'2026-09-07' -> '7 Sep' (portable: no %-d)."""
    d = date.fromisoformat(week)
    return f"{d.day} {d.strftime('%b')}"


def window_cutoff(weeks: int, now: Optional[datetime] = None) -> Optional[str]:
    """ISO timestamp `weeks` weeks before now, or None when weeks == 0 (all time)."""
    if not weeks:
        return None
    now = now or datetime.now()
    return (now - timedelta(weeks=weeks)).isoformat(timespec="seconds")


def _sector_clause(sector: Optional[str], column: str = "jobs.sector") -> str:
    return f" AND {column} = ?" if sector else ""


SENIORITY_LEVELS = ["Intern/Graduate", "Junior", "Mid", "Senior", "Lead/Principal", "Manager",
                    "Director+", "Not stated"]


@dataclass(frozen=True)
class JobRecord:
    """One job with its description and Claude's reading, as the dashboard
    shows it. Claude fields are None (lists empty) without an 'ok' reading."""
    id: int
    company: str
    title: str
    url: Optional[str]
    sector: str
    first_seen: str
    is_active: bool
    description: Optional[str]
    read_by_claude: bool
    role_family: Optional[str]
    seniority: Optional[str]
    min_years: Optional[int]
    work_mode: Optional[str]
    contract_type: Optional[str]
    salary_min: Optional[float]
    salary_max: Optional[float]
    salary_currency: Optional[str]
    salary_period: Optional[str]
    reason: Optional[str]
    skills: Tuple[str, ...]
    languages: Tuple[str, ...]


_RECORD_SQL = """
SELECT jobs.id, jobs.company, jobs.title, jobs.url, jobs.sector, jobs.first_seen, jobs.is_active,
       CASE WHEN job_details.enrichment_failed = 0 AND job_details.description != ''
            THEN job_details.description END AS description,
       job_insights.job_key IS NOT NULL AS read_by_claude,
       job_insights.role_family, job_insights.seniority, job_insights.min_years_experience,
       job_insights.work_mode, job_insights.contract_type, job_insights.salary_min,
       job_insights.salary_max, job_insights.salary_currency, job_insights.salary_period,
       job_insights.reason, job_insights.skills, job_insights.required_languages
FROM jobs
LEFT JOIN job_details ON job_details.job_id = jobs.id
LEFT JOIN job_insights ON job_insights.job_key = jobs.job_key AND job_insights.status = 'ok'
WHERE 1=1"""


def _json_tuple(text: Optional[str]) -> Tuple[str, ...]:
    return tuple(json.loads(text)) if text else ()


def job_records(conn, sector: Optional[str] = None, weeks: int = 0,
                now: Optional[datetime] = None) -> List[JobRecord]:
    """Every job, newest first, with its description and Claude's reading --
    the one query behind the Jobs page and every Claude-based chart. Scoped
    like the charts: a sector, and jobs first seen inside the window."""
    cutoff = window_cutoff(weeks, now)
    sql, params = _RECORD_SQL, []
    if cutoff:
        sql += " AND jobs.first_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND jobs.sector = ?"
        params.append(sector)
    sql += " ORDER BY jobs.first_seen DESC, jobs.id DESC"
    return [JobRecord(
        id=r["id"], company=r["company"], title=r["title"], url=r["url"], sector=r["sector"],
        first_seen=r["first_seen"], is_active=bool(r["is_active"]), description=r["description"],
        read_by_claude=bool(r["read_by_claude"]), role_family=r["role_family"],
        seniority=r["seniority"], min_years=r["min_years_experience"], work_mode=r["work_mode"],
        contract_type=r["contract_type"], salary_min=r["salary_min"], salary_max=r["salary_max"],
        salary_currency=r["salary_currency"], salary_period=r["salary_period"], reason=r["reason"],
        skills=_json_tuple(r["skills"]), languages=_json_tuple(r["required_languages"]),
    ) for r in conn.execute(sql, params)]


def _read_records(conn, sector: Optional[str], weeks: int, now: Optional[datetime]) -> List[JobRecord]:
    """The jobs Claude has read -- the base of every Claude-based chart."""
    return [r for r in job_records(conn, sector=sector, weeks=weeks, now=now) if r.read_by_claude]


def skill_key(name: str) -> str:
    """Claude spells the same skill several ways ("Distributed Systems" /
    "Distributed systems"); counting by this key merges them."""
    return name.strip().casefold()


def merge_skill_names(spellings: Counter) -> Dict[str, str]:
    """skill_key -> the spelling to show: the most frequent, ties alphabetical."""
    by_key: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
    for name, count in spellings.items():
        by_key[skill_key(name)].append((name.strip(), count))
    return {key: sorted(variants, key=lambda nc: (-nc[1], nc[0]))[0][0] for key, variants in by_key.items()}


def company_velocity(conn, sector: Optional[str] = None, weeks: int = 12,
                     now: Optional[datetime] = None) -> List[dict]:
    """Per company: open roles now, new roles in the window, and new roles in
    the equal-length window before it (None when weeks == 0)."""
    now = now or datetime.now()
    cutoff = window_cutoff(weeks, now)
    prev_cutoff = window_cutoff(2 * weeks, now) if weeks else None
    sql = """SELECT company, SUM(is_active) active,
                    SUM(CASE WHEN ? IS NULL OR first_seen >= ? THEN 1 ELSE 0 END) new_in_window,
                    SUM(CASE WHEN ? IS NOT NULL AND first_seen >= ? AND first_seen < ? THEN 1 ELSE 0 END) new_previous
             FROM jobs WHERE 1=1"""
    params: list = [cutoff, cutoff, prev_cutoff, prev_cutoff, cutoff]
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    sql += " GROUP BY company ORDER BY active DESC, company"
    return [{
        "company": r["company"],
        "active": r["active"] or 0,
        "new_in_window": r["new_in_window"] or 0,
        "new_previous_window": (r["new_previous"] or 0) if weeks else None,
    } for r in conn.execute(sql, params)]


def compute_movers(rows: List[dict], n: int = 3) -> dict:
    """Top-n risers and fallers by (new_in_window - new_previous_window).

    "comparable" is False when no row has any new_previous_window data (e.g.
    the previous window predates the earliest record) -- ranking by raw
    totals in that case would misleadingly credit every company as "rising"."""
    comparable = any((r["new_previous_window"] or 0) > 0 for r in rows)
    if not comparable:
        return {"up": [], "down": [], "comparable": False}
    deltas = [(r["company"], r["new_in_window"] - r["new_previous_window"])
              for r in rows if r["new_previous_window"] is not None]
    up = sorted((d for d in deltas if d[1] > 0), key=lambda d: (-d[1], d[0]))[:n]
    down = sorted((d for d in deltas if d[1] < 0), key=lambda d: (d[1], d[0]))[:n]
    return {"up": [{"company": c, "delta": v} for c, v in up],
            "down": [{"company": c, "delta": v} for c, v in down],
            "comparable": True}


def _week_range(cutoff: Optional[str], seen: Iterable[str], now: datetime) -> List[str]:
    """Continuous Monday dates from the window start (or the earliest week seen)
    to this week."""
    seen = list(seen)
    if cutoff:
        start = week_start(cutoff)
    elif seen:
        start = min(seen)
    else:
        return []
    end = week_start(now.isoformat(timespec="seconds"))
    out, d = [], date.fromisoformat(start)
    while d.isoformat() <= end:
        out.append(d.isoformat())
        d += timedelta(days=7)
    return out


def skill_trend(conn, sector: Optional[str] = None, weeks: int = 12, limit: int = 12,
                now: Optional[datetime] = None) -> List[dict]:
    """For the top `limit` skills in the window: jobs per week mentioning the
    skill (`count`) and enriched jobs first seen that week (`total`, the share
    denominator). Dense: one row per (skill, week), skill-major."""
    now = now or datetime.now()
    cutoff = window_cutoff(weeks, now)
    top = [r["skill"] for r in top_skills(conn, limit=limit, sector=sector, weeks=weeks, now=now)]
    if not top:
        return []
    window_sql = (" AND jobs.first_seen >= ?" if cutoff else "") + (" AND jobs.sector = ?" if sector else "")
    window_params: list = ([cutoff] if cutoff else []) + ([sector] if sector else [])
    totals = Counter(
        week_start(r["first_seen"]) for r in conn.execute(
            "SELECT jobs.first_seen FROM job_details JOIN jobs ON jobs.id = job_details.job_id"
            " WHERE job_details.enrichment_failed = 0" + window_sql, window_params))
    placeholders = ", ".join("?" for _ in top)
    per: Counter = Counter()
    for r in conn.execute(
        "SELECT jobs.first_seen AS first_seen, skills.name AS name"
        " FROM job_skills JOIN skills ON skills.id = job_skills.skill_id"
        " JOIN job_details ON job_details.job_id = job_skills.job_id"
        " JOIN jobs ON jobs.id = job_skills.job_id"
        " WHERE job_details.enrichment_failed = 0" + window_sql +
        f" AND skills.name IN ({placeholders})",
        window_params + top,
    ):
        per[(r["name"], week_start(r["first_seen"]))] += 1
    weeks_out = _week_range(cutoff, totals.keys(), now)
    return [{"week": w, "skill": s, "count": per.get((s, w), 0), "total": totals.get(w, 0)}
            for s in top for w in weeks_out]


def seniority_by_company(conn, sector: Optional[str] = None, weeks: int = 12,
                         now: Optional[datetime] = None) -> List[dict]:
    cutoff = window_cutoff(weeks, now)
    sql = """SELECT jobs.company AS company, COALESCE(job_details.seniority, 'Unspecified') AS seniority,
                    COUNT(*) AS count
             FROM job_details JOIN jobs ON jobs.id = job_details.job_id
             WHERE job_details.enrichment_failed = 0"""
    params: list = []
    if cutoff:
        sql += " AND jobs.first_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND jobs.sector = ?"
        params.append(sector)
    sql += " GROUP BY jobs.company, seniority ORDER BY jobs.company, seniority"
    return [{"company": r["company"], "seniority": r["seniority"], "count": r["count"]}
            for r in conn.execute(sql, params)]


def new_jobs_per_week(conn, weeks: int = 12, sector: Optional[str] = None,
                      now: Optional[datetime] = None) -> List[dict]:
    """New jobs per ISO week as a continuous, zero-filled series ending this
    week. `week` is the Monday date. weeks=0 starts at the earliest job."""
    now = now or datetime.now()
    cutoff = window_cutoff(weeks, now)
    sql, params = "SELECT first_seen FROM jobs WHERE 1=1", []
    if cutoff:
        sql += " AND first_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    counts = Counter(week_start(r["first_seen"]) for r in conn.execute(sql, params))
    if cutoff:
        start = week_start(cutoff)
    elif counts:
        start = min(counts)
    else:
        return []
    end = week_start(now.isoformat(timespec="seconds"))
    out, d = [], date.fromisoformat(start)
    while d.isoformat() <= end:
        out.append({"week": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
        d += timedelta(days=7)
    return out


def category_breakdown(conn, sector: Optional[str] = None, weeks: int = 0,
                       now: Optional[datetime] = None) -> List[dict]:
    cutoff = window_cutoff(weeks, now)
    sql, params = "SELECT company, title FROM jobs WHERE 1=1", []
    if cutoff:
        sql += " AND first_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    counts: Dict[tuple, int] = {}
    for r in conn.execute(sql, params):
        key = (r["company"], categorize(r["title"]))
        counts[key] = counts.get(key, 0) + 1
    return [{"company": c, "category": cat, "count": n} for (c, cat), n in sorted(counts.items())]


def median_days_active(conn, sector: Optional[str] = None, weeks: int = 0,
                       min_closed: int = 1, now: Optional[datetime] = None) -> List[dict]:
    """Median days between first and last sighting for jobs that have closed
    (is_active = 0) whose last sighting falls in the window."""
    cutoff = window_cutoff(weeks, now)
    sql, params = "SELECT company, first_seen, last_seen FROM jobs WHERE is_active = 0", []
    if cutoff:
        sql += " AND last_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    spans: Dict[str, List[float]] = {}
    for r in conn.execute(sql, params):
        days = (datetime.fromisoformat(r["last_seen"]) - datetime.fromisoformat(r["first_seen"])).total_seconds() / 86400
        spans.setdefault(r["company"], []).append(days)
    return [{"company": c, "median_days": round(statistics.median(v), 1), "closed": len(v)}
            for c, v in sorted(spans.items()) if len(v) >= min_closed]


def overview(conn, sector: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
    two_weeks_ago = (now - timedelta(days=14)).isoformat(timespec="seconds")
    where = " WHERE sector = ?" if sector else ""
    and_sector = _sector_clause(sector, "sector")
    p = [sector] if sector else []

    def count(sql, params):
        return conn.execute(sql, params).fetchone()["c"]

    total = count("SELECT COUNT(*) c FROM jobs" + where, p)
    enriched = count(
        "SELECT COUNT(*) c FROM job_details JOIN jobs ON jobs.id = job_details.job_id"
        " WHERE job_details.enrichment_failed = 0" + _sector_clause(sector, "jobs.sector"), p)
    last_run = conn.execute(
        "SELECT * FROM runs" + where + " ORDER BY id DESC LIMIT 1", p).fetchone()
    return {
        "active_jobs": count("SELECT COUNT(*) c FROM jobs WHERE is_active = 1" + and_sector, p),
        "total_jobs_seen": total,
        "new_this_week": count("SELECT COUNT(*) c FROM jobs WHERE first_seen >= ?" + and_sector, [week_ago] + p),
        "new_previous_week": count(
            "SELECT COUNT(*) c FROM jobs WHERE first_seen >= ? AND first_seen < ?" + and_sector,
            [two_weeks_ago, week_ago] + p),
        "closed_last_7d": count(
            "SELECT COUNT(*) c FROM jobs WHERE is_active = 0 AND last_seen >= ?" + and_sector, [week_ago] + p),
        "companies": count("SELECT COUNT(DISTINCT company) c FROM jobs" + where, p),
        "companies_failing": count("SELECT COUNT(*) c FROM company_failures" + where, p),
        "enriched_count": enriched,
        "enriched_pct": round(100 * enriched / total) if total else 0,
        "last_run": dict(last_run) if last_run else None,
        "emails_sent": count("SELECT COUNT(*) c FROM emails WHERE success = 1", []),
        "emails_failed": count("SELECT COUNT(*) c FROM emails WHERE success = 0", []),
    }


def top_skills(conn, limit: int = 15, sector: Optional[str] = None, weeks: int = 0,
               now: Optional[datetime] = None) -> List[dict]:
    cutoff = window_cutoff(weeks, now)
    sql = """SELECT skills.name AS skill, skills.category AS category, COUNT(*) AS count
             FROM job_skills
             JOIN skills ON skills.id = job_skills.skill_id
             JOIN job_details ON job_details.job_id = job_skills.job_id
             JOIN jobs ON jobs.id = job_skills.job_id
             WHERE job_details.enrichment_failed = 0"""
    params: list = []
    if cutoff:
        sql += " AND jobs.first_seen >= ?"
        params.append(cutoff)
    if sector:
        sql += " AND jobs.sector = ?"
        params.append(sector)
    sql += " GROUP BY skills.id ORDER BY count DESC, skills.name LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [{"skill": r["skill"], "category": r["category"], "count": r["count"]} for r in rows]


_STATUS_ORDER = {"failing": 0, "empty": 1, "retired": 2, "ok": 3}


def scraper_health(conn, registries: Dict[str, Iterable[str]]) -> List[dict]:
    """One row per (sector, company) known to either the DB or a scraper
    registry. Status is derived, never stored:
      retired  -- has rows but is in no registry (e.g. Johnson & Johnson)
      failing  -- company_failures holds an exception message
      empty    -- company_failures holds the zero-listing warning
      ok       -- everything else (including registry entries with no rows yet)"""
    scraped = {(sector, company) for sector, names in registries.items() for company in names}
    failures = {(r["sector"], r["company"]): r["last_error"]
                for r in conn.execute("SELECT sector, company, last_error FROM company_failures")}
    rows = conn.execute(
        "SELECT sector, company, SUM(is_active) active, MAX(last_seen) last_seen"
        " FROM jobs GROUP BY sector, company").fetchall()
    db = {(r["sector"], r["company"]): r for r in rows}
    out = []
    for key in set(db) | scraped:
        r = db.get(key)
        error = failures.get(key)
        if key not in scraped:
            status = "retired"
        elif error is None:
            status = "ok"
        elif error.startswith("returned 0 jobs"):
            status = "empty"
        else:
            status = "failing"
        out.append({"sector": key[0], "company": key[1], "status": status,
                    "active": (r["active"] or 0) if r else 0,
                    "last_seen": r["last_seen"] if r else None, "error": error})
    return sorted(out, key=lambda x: (_STATUS_ORDER[x["status"]], x["sector"], x["company"]))


def run_history(conn, sector: str, limit: int = 20) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM runs WHERE sector = ? ORDER BY id DESC LIMIT ?", (sector, limit)).fetchall()
    out = []
    for r in rows:
        duration = None
        if r["finished_at"]:
            duration = round((datetime.fromisoformat(r["finished_at"])
                              - datetime.fromisoformat(r["started_at"])).total_seconds())
        failed = list(json.loads(r["failed_companies"]).keys()) if r["failed_companies"] else []
        out.append({"started_at": r["started_at"], "duration_s": duration,
                    "total_jobs": r["total_jobs"], "new_jobs": r["new_jobs"], "failed": failed})
    return out


def claude_usage(conn, today: date) -> dict:
    """The health page's Claude API panel: this month's spend, today's
    realtime calls against the daily cap, readings by status, and the
    current key/credit problem if there is one."""
    from jobfinder import config, storage
    return {
        "month_spend": storage.insight_spend(conn, today.replace(day=1).isoformat()),
        "calls_today": storage.insight_calls_on(conn, today.isoformat()),
        "daily_limit": config.INSIGHTS_DAILY_CALL_LIMIT,
        "statuses": storage.insight_status_counts(conn),
        "error": storage.get_failing_companies(conn, config.INSIGHTS_ALERT_SECTOR)
                        .get(config.INSIGHTS_ALERT_NAME),
    }


def _ranked_skills(records: List[JobRecord], limit: int) -> List[Tuple[str, str, int]]:
    """(key, display name, roles) for the `limit` skills most roles need. A
    role counts once per merged skill; ties go to the alphabetically first."""
    spellings: Counter = Counter()
    per_key: Counter = Counter()
    for r in records:
        keys = set()
        for name in r.skills:
            spellings[name] += 1
            keys.add(skill_key(name))
        per_key.update(keys)
    names = merge_skill_names(spellings)
    ranked = sorted(per_key.items(), key=lambda kv: (-kv[1], names[kv[0]]))[:limit]
    return [(key, names[key], count) for key, count in ranked]


def _in_roles(r: JobRecord, families: Iterable[str], levels: Iterable[str]) -> bool:
    """Is the role in the chosen role families and levels? Nothing chosen = all."""
    families, levels = tuple(families), tuple(levels)
    return ((not families or r.role_family in families)
            and (not levels or (r.seniority or "Not stated") in levels))


def skill_demand(conn, sector: Optional[str] = None, weeks: int = 0, limit: int = 15,
                 now: Optional[datetime] = None) -> List[dict]:
    """The skills most roles need, among roles Claude read in the window."""
    records = _read_records(conn, sector, weeks, now)
    return [{"skill": name, "count": count} for _, name, count in _ranked_skills(records, limit)]


def skill_shares_by_week(conn, sector: Optional[str] = None, weeks: int = 12, limit: int = 12,
                         now: Optional[datetime] = None) -> List[dict]:
    """For the top `limit` skills: roles needing the skill per week (`count`)
    and roles Claude read that week (`total`, the share denominator). Dense:
    one row per (skill, week), skill-major."""
    now = now or datetime.now()
    records = _read_records(conn, sector, weeks, now)
    ranked = _ranked_skills(records, limit)
    if not ranked:
        return []
    totals = Counter(week_start(r.first_seen) for r in records)
    per: Counter = Counter()
    for r in records:
        week = week_start(r.first_seen)
        for key in {skill_key(name) for name in r.skills}:
            per[(key, week)] += 1
    weeks_out = _week_range(window_cutoff(weeks, now), totals.keys(), now)
    return [{"week": w, "skill": name, "count": per.get((key, w), 0), "total": totals.get(w, 0)}
            for key, name, _ in ranked for w in weeks_out]


def seniority_counts(conn, sector: Optional[str] = None, weeks: int = 12,
                     now: Optional[datetime] = None) -> List[dict]:
    counts = Counter((r.company, r.seniority or "Not stated") for r in _read_records(conn, sector, weeks, now))
    return [{"company": c, "seniority": s, "count": n} for (c, s), n in sorted(counts.items())]


def family_counts(conn, sector: Optional[str] = None, weeks: int = 0,
                  now: Optional[datetime] = None) -> List[dict]:
    counts = Counter((r.company, r.role_family) for r in _read_records(conn, sector, weeks, now)
                     if r.role_family)
    return [{"company": c, "family": f, "count": n} for (c, f), n in sorted(counts.items())]


DRILLDOWN_LIMIT = 100


def claude_drilldown(conn, dimension: str, value: str, sector: Optional[str] = None, weeks: int = 0,
                     families: Iterable[str] = (), levels: Iterable[str] = (),
                     now: Optional[datetime] = None) -> Optional[List[dict]]:
    """The roles Claude read behind a chart value, newest first (at most
    DRILLDOWN_LIMIT). None when this function doesn't handle `dimension`."""
    if dimension == "skill":
        key = skill_key(value)

        def match(r):
            return key in {skill_key(name) for name in r.skills} and _in_roles(r, families, levels)
    elif dimension == "seniority":
        def match(r):
            return (r.seniority or "Not stated") == value
    elif dimension == "role_family":
        def match(r):
            return r.role_family == value
    elif dimension == "company_family":
        company, _, family = value.partition("::")

        def match(r):
            return r.company == company and r.role_family == family
    else:
        return None
    return [{"title": r.title, "company": r.company, "url": r.url, "first_seen": r.first_seen}
            for r in _read_records(conn, sector, weeks, now) if match(r)][:DRILLDOWN_LIMIT]
