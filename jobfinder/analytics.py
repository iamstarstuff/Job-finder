from __future__ import annotations

import json
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

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
