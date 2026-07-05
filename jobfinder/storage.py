from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List

from jobfinder.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    portal_url TEXT,
    closing_date TEXT,
    job_key TEXT NOT NULL UNIQUE,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    total_jobs INTEGER,
    new_jobs INTEGER,
    failed_companies TEXT
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY,
    sent_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT,
    recipients TEXT,
    success INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen);
"""


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_company_snapshot(conn, company: str, jobs: List[Job], now: str) -> List[Job]:
    new_jobs = []
    seen_keys = set()
    for job in jobs:
        if job.key in seen_keys:
            continue  # duplicate within one scrape
        seen_keys.add(job.key)
        row = conn.execute("SELECT id FROM jobs WHERE job_key = ?", (job.key,)).fetchone()
        if row:
            conn.execute(
                "UPDATE jobs SET last_seen = ?, is_active = 1, title = ?, closing_date = ? WHERE id = ?",
                (now, job.title, job.closing_date, row["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO jobs (company, title, url, portal_url, closing_date,
                   job_key, first_seen, last_seen, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (job.company, job.title, job.url, job.portal_url,
                 job.closing_date, job.key, now, now),
            )
            new_jobs.append(job)
    # Deactivate jobs for this company that vanished from the site.
    active = conn.execute(
        "SELECT id, job_key FROM jobs WHERE company = ? AND is_active = 1", (company,)
    ).fetchall()
    for row in active:
        if row["job_key"] not in seen_keys:
            conn.execute("UPDATE jobs SET is_active = 0 WHERE id = ?", (row["id"],))
    conn.commit()
    return new_jobs


def start_run(conn, started_at: str) -> int:
    cur = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started_at,))
    conn.commit()
    return cur.lastrowid


def finish_run(conn, run_id: int, finished_at: str, total_jobs: int,
               new_jobs: int, failed_companies: Dict[str, str]) -> None:
    conn.execute(
        "UPDATE runs SET finished_at = ?, total_jobs = ?, new_jobs = ?, failed_companies = ? WHERE id = ?",
        (finished_at, total_jobs, new_jobs, json.dumps(failed_companies), run_id),
    )
    conn.commit()


def log_email(conn, sent_at: str, kind: str, subject: str,
              recipients: List[str], success: bool, error: str = None) -> None:
    conn.execute(
        "INSERT INTO emails (sent_at, kind, subject, recipients, success, error) VALUES (?, ?, ?, ?, ?, ?)",
        (sent_at, kind, subject, json.dumps(recipients), 1 if success else 0, error),
    )
    conn.commit()


def migrate_legacy_json(conn, json_path, now: str) -> int:
    path = Path(json_path)
    if not path.exists():
        return 0
    if conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"] > 0:
        return 0  # already migrated
    data = json.loads(path.read_text())
    count = 0
    for company, jobs in data.items():
        for item in jobs:
            url = item.get("application url") or item.get("application link") or ""
            job = Job(
                company=item.get("company", company),
                title=item.get("title", ""),
                url=url,
                portal_url=item.get("job portal link", ""),
                closing_date=item.get("closing_date"),
            )
            row = conn.execute("SELECT id FROM jobs WHERE job_key = ?", (job.key,)).fetchone()
            if not row:
                conn.execute(
                    """INSERT INTO jobs (company, title, url, portal_url, closing_date,
                       job_key, first_seen, last_seen, is_active)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (job.company, job.title, job.url, job.portal_url,
                     job.closing_date, job.key, now, now),
                )
                count += 1
    conn.commit()
    return count
