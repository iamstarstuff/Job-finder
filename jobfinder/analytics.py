from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import List

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
    ("IT / Digital", ["it ", "digital", "data", "software", "system"]),
    ("Commercial", ["sales", "marketing", "commercial", "account",
                    "business development", "product specialist"]),
    ("HR / Finance / Admin", ["hr", "human resources", "finance", "accountant",
                              "administrat", "payroll", "legal"]),
]


def categorize(title: str) -> str:
    lowered = f" {title.lower()} "
    for category, keywords in CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return category
    return "Other"


def jobs_per_company(conn) -> List[dict]:
    rows = conn.execute(
        """SELECT company, COUNT(*) total, SUM(is_active) active
           FROM jobs GROUP BY company ORDER BY company"""
    ).fetchall()
    return [{"company": r["company"], "total": r["total"], "active": r["active"] or 0}
            for r in rows]


def new_jobs_per_week(conn, weeks: int = 12) -> List[dict]:
    cutoff = (datetime.now() - timedelta(weeks=weeks)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT strftime('%Y-%W', first_seen) week, COUNT(*) count
           FROM jobs WHERE first_seen >= ? GROUP BY week ORDER BY week""",
        (cutoff,),
    ).fetchall()
    return [{"week": r["week"], "count": r["count"]} for r in rows]


def category_breakdown(conn) -> List[dict]:
    rows = conn.execute("SELECT company, title FROM jobs").fetchall()
    counts = {}
    for r in rows:
        key = (r["company"], categorize(r["title"]))
        counts[key] = counts.get(key, 0) + 1
    return [{"company": c, "category": cat, "count": n}
            for (c, cat), n in sorted(counts.items())]


def median_days_active(conn) -> List[dict]:
    rows = conn.execute(
        "SELECT company, first_seen, last_seen FROM jobs WHERE is_active = 0"
    ).fetchall()
    spans = {}
    for r in rows:
        days = (datetime.fromisoformat(r["last_seen"])
                - datetime.fromisoformat(r["first_seen"])).total_seconds() / 86400
        spans.setdefault(r["company"], []).append(days)
    return [{"company": c, "median_days": round(statistics.median(v), 1)}
            for c, v in sorted(spans.items())]


def overview(conn) -> dict:
    week_ago = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    last_run = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return {
        "active_jobs": conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE is_active = 1").fetchone()["c"],
        "total_jobs_seen": conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
        "new_this_week": conn.execute(
            "SELECT COUNT(*) c FROM jobs WHERE first_seen >= ?", (week_ago,)).fetchone()["c"],
        "companies": conn.execute(
            "SELECT COUNT(DISTINCT company) c FROM jobs").fetchone()["c"],
        "last_run": dict(last_run) if last_run else None,
        "emails_sent": conn.execute(
            "SELECT COUNT(*) c FROM emails WHERE success = 1").fetchone()["c"],
        "emails_failed": conn.execute(
            "SELECT COUNT(*) c FROM emails WHERE success = 0").fetchone()["c"],
    }
