from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import List, Optional

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


def new_jobs_per_week(conn, weeks: int = 12, sector: Optional[str] = None) -> List[dict]:
    cutoff = (datetime.now() - timedelta(weeks=weeks)).isoformat(timespec="seconds")
    sql = "SELECT strftime('%Y-%W', first_seen) week, COUNT(*) count FROM jobs WHERE first_seen >= ?"
    params = [cutoff]
    if sector:
        sql += " AND sector = ?"
        params.append(sector)
    sql += " GROUP BY week ORDER BY week"
    rows = conn.execute(sql, params).fetchall()
    return [{"week": r["week"], "count": r["count"]} for r in rows]


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


def overview(conn, sector: Optional[str] = None) -> dict:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    jobs_where = " WHERE sector = ?" if sector else ""
    jobs_params = [sector] if sector else []

    active_sql = "SELECT COUNT(*) c FROM jobs WHERE is_active = 1" + (" AND sector = ?" if sector else "")
    total_sql = "SELECT COUNT(*) c FROM jobs" + jobs_where
    new_sql = "SELECT COUNT(*) c FROM jobs WHERE first_seen >= ?" + (" AND sector = ?" if sector else "")
    companies_sql = "SELECT COUNT(DISTINCT company) c FROM jobs" + jobs_where

    last_run_sql = "SELECT * FROM runs" + (" WHERE sector = ?" if sector else "") + " ORDER BY id DESC LIMIT 1"
    last_run = conn.execute(last_run_sql, jobs_params).fetchone()

    return {
        "active_jobs": conn.execute(active_sql, jobs_params).fetchone()["c"],
        "total_jobs_seen": conn.execute(total_sql, jobs_params).fetchone()["c"],
        "new_this_week": conn.execute(new_sql, [week_ago] + jobs_params).fetchone()["c"],
        "companies": conn.execute(companies_sql, jobs_params).fetchone()["c"],
        "last_run": dict(last_run) if last_run else None,
        "emails_sent": conn.execute(
            "SELECT COUNT(*) c FROM emails WHERE success = 1").fetchone()["c"],
        "emails_failed": conn.execute(
            "SELECT COUNT(*) c FROM emails WHERE success = 0").fetchone()["c"],
    }


def top_skills(conn, limit: int = 15, sector: Optional[str] = None) -> List[dict]:
    sql = """SELECT skills.name AS skill, skills.category AS category, COUNT(*) AS count
             FROM job_skills
             JOIN skills ON skills.id = job_skills.skill_id
             JOIN job_details ON job_details.job_id = job_skills.job_id
             JOIN jobs ON jobs.id = job_skills.job_id
             WHERE job_details.enrichment_failed = 0"""
    params = []
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
