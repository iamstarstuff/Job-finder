from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
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


def jobs_per_company(conn, sector: Optional[str] = None) -> List[dict]:
    sql = "SELECT company, COUNT(*) total, SUM(is_active) active FROM jobs"
    params = []
    if sector:
        sql += " WHERE sector = ?"
        params.append(sector)
    sql += " GROUP BY company ORDER BY company"
    rows = conn.execute(sql, params).fetchall()
    return [{"company": r["company"], "total": r["total"], "active": r["active"] or 0}
            for r in rows]


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


def category_breakdown(conn, sector: Optional[str] = None) -> List[dict]:
    sql = "SELECT company, title FROM jobs"
    params = []
    if sector:
        sql += " WHERE sector = ?"
        params.append(sector)
    rows = conn.execute(sql, params).fetchall()
    counts = {}
    for r in rows:
        key = (r["company"], categorize(r["title"]))
        counts[key] = counts.get(key, 0) + 1
    return [{"company": c, "category": cat, "count": n}
            for (c, cat), n in sorted(counts.items())]


def median_days_active(conn, sector: Optional[str] = None) -> List[dict]:
    sql = "SELECT company, first_seen, last_seen FROM jobs WHERE is_active = 0"
    params = []
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    rows = conn.execute(sql, params).fetchall()
    spans = {}
    for r in rows:
        days = (datetime.fromisoformat(r["last_seen"])
                - datetime.fromisoformat(r["first_seen"])).total_seconds() / 86400
        spans.setdefault(r["company"], []).append(days)
    return [{"company": c, "median_days": round(statistics.median(v), 1)}
            for c, v in sorted(spans.items())]


def overview(conn, sector: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat(timespec="seconds")
    two_weeks_ago = (now - timedelta(days=14)).isoformat(timespec="seconds")
    where = " WHERE sector = ?" if sector else ""
    and_sector = " AND sector = ?" if sector else ""
    p = [sector] if sector else []

    def count(sql, params):
        return conn.execute(sql, params).fetchone()["c"]

    total = count("SELECT COUNT(*) c FROM jobs" + where, p)
    enriched = count(
        "SELECT COUNT(*) c FROM job_details JOIN jobs ON jobs.id = job_details.job_id"
        " WHERE job_details.enrichment_failed = 0" + and_sector.replace("sector", "jobs.sector"), p)
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


def seniority_breakdown(conn, sector: Optional[str] = None) -> List[dict]:
    sql = """SELECT COALESCE(job_details.seniority, 'Unspecified') AS seniority, COUNT(*) AS count
             FROM job_details
             JOIN jobs ON jobs.id = job_details.job_id
             WHERE job_details.enrichment_failed = 0"""
    params = []
    if sector:
        sql += " AND jobs.sector = ?"
        params.append(sector)
    sql += " GROUP BY COALESCE(job_details.seniority, 'Unspecified') ORDER BY count DESC"
    rows = conn.execute(sql, params).fetchall()
    return [{"seniority": r["seniority"], "count": r["count"]} for r in rows]


def skills_by_category(conn, sector: Optional[str] = None) -> List[dict]:
    sql = """SELECT skills.category AS category, skills.name AS skill, COUNT(*) AS count
             FROM job_skills
             JOIN skills ON skills.id = job_skills.skill_id
             JOIN job_details ON job_details.job_id = job_skills.job_id
             JOIN jobs ON jobs.id = job_skills.job_id
             WHERE job_details.enrichment_failed = 0"""
    params = []
    if sector:
        sql += " AND jobs.sector = ?"
        params.append(sector)
    sql += " GROUP BY skills.id ORDER BY category, count DESC"
    rows = conn.execute(sql, params).fetchall()
    return [{"category": r["category"], "skill": r["skill"], "count": r["count"]} for r in rows]
