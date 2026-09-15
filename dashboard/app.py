from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# allow running as a script: python dashboard/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from dashboard import brief, charts
from jobfinder import analytics, config, storage

WINDOWS = (0, 4, 12, 26)
WINDOW_OPTIONS = [(4, "Last 4 weeks"), (12, "Last 12 weeks"), (26, "Last 26 weeks"), (0, "All time")]
WINDOW_LABELS = {4: "over the last 4 weeks", 12: "over the last 12 weeks",
                 26: "over the last 26 weeks", 0: "across everything tracked"}

SECTOR_NAMES = {"": "pharma and tech", "pharma": "pharma", "tech": "tech"}


def _page_context(conn, sector: str, weeks: int) -> dict:
    """Everything the Home and sector templates share: filters, tiles, the
    brief and the movers list. `sector` is "" for the combined view."""
    scoped = sector or None
    overview = analytics.overview(conn, sector=scoped)
    velocity = analytics.company_velocity(conn, sector=scoped, weeks=weeks)
    this_week = analytics.company_velocity(conn, sector=scoped, weeks=1)
    return {
        "sector": sector,
        "weeks": weeks,
        "window_options": WINDOW_OPTIONS,
        "overview": overview,
        "kicker": f"This week in Irish {SECTOR_NAMES[sector]} hiring",
        "brief": brief.compose_brief(
            overview, analytics.top_skills(conn, limit=3, sector=scoped, weeks=weeks),
            this_week, WINDOW_LABELS[weeks]),
        "movers": analytics.compute_movers(velocity) if weeks else None,
    }


def _window_arg() -> int:
    """?weeks= as an int from WINDOWS; default 12; anything else is a 400."""
    raw = request.args.get("weeks", "12")
    try:
        weeks = int(raw)
    except ValueError:
        abort(400)
    if weeks not in WINDOWS:
        abort(400)
    return weeks


def _sector_arg() -> str:
    sector = request.args.get("sector", "")
    return sector if sector in ("pharma", "tech") else ""


def highlight(text, term):
    """Escape `text` for safe HTML output, then wrap case-insensitive
    matches of `term` in <mark>. Both text and term are escaped before any
    matching happens, so this is safe even if either contains HTML — the
    only unescaped markup ever introduced is the literal <mark>/</mark>
    tags this function writes itself, never anything derived from input."""
    escaped_text = str(escape(text or ""))
    if not term:
        return Markup(escaped_text)
    escaped_term = str(escape(term))
    pattern = re.compile(re.escape(escaped_term), re.IGNORECASE)
    return Markup(pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped_text))


def create_app(db_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or config.DB_PATH)
    app.jinja_env.filters["highlight"] = highlight

    def get_conn():
        if "conn" not in g:
            g.conn = storage.connect(app.config["DB_PATH"])
        return g.conn

    @app.teardown_appcontext
    def close_conn(exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.route("/")
    def index():
        return render_template("index.html", **_page_context(get_conn(), _sector_arg(), _window_arg()))

    @app.route("/sector/<name>")
    def sector_page(name):
        if name not in ("pharma", "tech"):
            return "Unknown sector", 404
        conn = get_conn()
        weeks = _window_arg()
        sql = """SELECT jobs.*, job_details.description, job_details.seniority,
                         job_details.enrichment_failed
                  FROM jobs LEFT JOIN job_details ON job_details.job_id = jobs.id
                  WHERE jobs.sector = ?
                  ORDER BY jobs.first_seen DESC LIMIT 10"""
        rows = conn.execute(sql, (name,)).fetchall()
        job_ids = [r["id"] for r in rows]
        skills_by_job = {}
        if job_ids:
            placeholders = ", ".join("?" for _ in job_ids)
            skill_rows = conn.execute(
                f"""SELECT job_skills.job_id, skills.name
                    FROM job_skills JOIN skills ON skills.id = job_skills.skill_id
                    WHERE job_skills.job_id IN ({placeholders})""",
                job_ids,
            ).fetchall()
            for r in skill_rows:
                skills_by_job.setdefault(r["job_id"], []).append(r["name"])
        return render_template("sector.html", recent_jobs=rows, skills_by_job=skills_by_job,
                               **_page_context(conn, name, weeks))

    @app.route("/jobs")
    def jobs():
        conn = get_conn()
        company = request.args.get("company", "")
        query = request.args.get("q", "")
        skill_query = request.args.get("skill", "")
        active = request.args.get("active", "")
        sector = request.args.get("sector", "")
        sql = """SELECT jobs.*, job_details.description, job_details.seniority,
                         job_details.enrichment_failed
                  FROM jobs LEFT JOIN job_details ON job_details.job_id = jobs.id
                  WHERE 1=1"""
        params = []
        if sector:
            sql += " AND jobs.sector = ?"
            params.append(sector)
        if company:
            sql += " AND jobs.company = ?"
            params.append(company)
        if query:
            sql += " AND jobs.title LIKE ?"
            params.append(f"%{query}%")
        if skill_query:
            sql += " AND job_details.description LIKE ?"
            params.append(f"%{skill_query}%")
        if active == "1":
            sql += " AND jobs.is_active = 1"
        sql += " ORDER BY jobs.first_seen DESC LIMIT 500"
        rows = conn.execute(sql, params).fetchall()

        job_ids = [r["id"] for r in rows]
        skills_by_job = {}
        if job_ids:
            placeholders = ", ".join("?" for _ in job_ids)
            skill_rows = conn.execute(
                f"""SELECT job_skills.job_id, skills.name
                    FROM job_skills JOIN skills ON skills.id = job_skills.skill_id
                    WHERE job_skills.job_id IN ({placeholders})""",
                job_ids,
            ).fetchall()
            for r in skill_rows:
                skills_by_job.setdefault(r["job_id"], []).append(r["name"])

        companies = [r["company"] for r in conn.execute(
            "SELECT DISTINCT company FROM jobs ORDER BY company")]
        return render_template("jobs.html", jobs=rows, companies=companies,
                               company=company, q=query, skill=skill_query, active=active,
                               sector=sector, skills_by_job=skills_by_job)

    @app.route("/api/drilldown/<dimension>")
    def api_drilldown(dimension):
        conn = get_conn()
        value = request.args.get("value", "")
        sector = request.args.get("sector") or None
        if dimension == "company":
            sql = "SELECT title, company, url, first_seen FROM jobs WHERE company = ?"
            params = [value]
            if sector:
                sql += " AND sector = ?"
                params.append(sector)
            sql += " ORDER BY first_seen DESC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
        elif dimension == "skill":
            sql = """SELECT jobs.title, jobs.company, jobs.url, jobs.first_seen
                     FROM jobs
                     JOIN job_skills ON job_skills.job_id = jobs.id
                     JOIN skills ON skills.id = job_skills.skill_id
                     WHERE skills.name = ?"""
            params = [value]
            if sector:
                sql += " AND jobs.sector = ?"
                params.append(sector)
            sql += " ORDER BY jobs.first_seen DESC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
        elif dimension == "seniority":
            seniority_value = None if value == "Unspecified" else value
            sql = """SELECT jobs.title, jobs.company, jobs.url, jobs.first_seen
                     FROM jobs
                     JOIN job_details ON job_details.job_id = jobs.id
                     WHERE job_details.seniority IS ? AND job_details.enrichment_failed = 0"""
            params = [seniority_value]
            if sector:
                sql += " AND jobs.sector = ?"
                params.append(sector)
            sql += " ORDER BY jobs.first_seen DESC LIMIT 100"
            rows = conn.execute(sql, params).fetchall()
        elif dimension == "category":
            sql = "SELECT title, company, url, first_seen FROM jobs"
            params = []
            if sector:
                sql += " WHERE sector = ?"
                params.append(sector)
            sql += " ORDER BY first_seen DESC"
            all_jobs = conn.execute(sql, params).fetchall()
            rows = [r for r in all_jobs if analytics.categorize(r["title"]) == value][:100]
        else:
            return jsonify({"error": "unknown dimension"}), 400
        return jsonify([
            {"title": r["title"], "company": r["company"], "url": r["url"], "first_seen": r["first_seen"]}
            for r in rows
        ])

    @app.route("/api/charts/<name>")
    def api_chart(name):
        builder = charts.CHARTS.get(name)
        if builder is None:
            abort(404)
        payload = builder(get_conn(), _sector_arg() or None, _window_arg())
        return jsonify(payload.to_dict())

    @app.route("/analytics")
    def analytics_page():
        return redirect(url_for("index"), code=302)

    @app.route("/emails")
    def emails_page():
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM emails ORDER BY id DESC LIMIT 200").fetchall()
        stats = conn.execute(
            """SELECT kind, COUNT(*) total, SUM(success) ok
               FROM emails GROUP BY kind""").fetchall()
        return render_template("emails.html", emails=rows, stats=stats)

    @app.route("/logs")
    def logs_page():
        log_files = {"pharma": config.LOG_PATH, "tech": config.TECH_LOG_PATH, "enrichment": config.ENRICHMENT_LOG_PATH}
        selected = request.args.get("log", "pharma")
        if selected not in log_files:
            selected = "pharma"
        try:
            lines = log_files[selected].read_text().splitlines()[-300:]
        except FileNotFoundError:
            lines = ["(no log file yet)"]
        return render_template("logs.html", lines=lines, selected_log=selected)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=False)
