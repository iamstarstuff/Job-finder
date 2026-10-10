from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

# allow running as a script: python dashboard/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, abort, g, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from dashboard import brief, charts, job_search
from jobfinder import analytics, config, storage
from jobfinder.scrapers import SCRAPERS
from jobfinder.tech_scrapers import TECH_SCRAPERS

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
            overview, analytics.skill_demand(conn, sector=scoped, weeks=weeks, limit=3),
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


def _drilldown_weeks() -> int:
    """?weeks= for drilldowns: validated like _window_arg, but all time when
    absent, so drilldown links without it keep listing every role."""
    if "weeks" not in request.args:
        return 0
    return _window_arg()


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


def short_date(iso_ts: str) -> str:
    """'2026-10-03T08:20:00' -> '3 Oct'."""
    return analytics.week_label(iso_ts[:10])


def create_app(db_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or config.DB_PATH)
    app.jinja_env.filters["highlight"] = highlight
    app.jinja_env.filters["short_date"] = short_date
    app.jinja_env.globals["card_facts"] = job_search.card_facts

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
        recent = analytics.job_records(conn, sector=name)[:10]
        return render_template("sector.html", recent_jobs=recent,
                               families=analytics.families_in(conn, name), levels=analytics.SENIORITY_LEVELS,
                               **_page_context(conn, name, weeks))

    @app.route("/jobs")
    def jobs():
        records = analytics.job_records(get_conn())
        result = job_search.search(records, job_search.Filters.from_args(request.args))
        return render_template("jobs.html", result=result)

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
            rows = [{"title": r["title"], "company": r["company"], "url": r["url"],
                     "first_seen": r["first_seen"]} for r in conn.execute(sql, params)]
        else:
            rows = analytics.claude_drilldown(
                conn, dimension, value, sector=sector, weeks=_drilldown_weeks(),
                families=request.args.getlist("family"), levels=request.args.getlist("level"))
            if rows is None:
                return jsonify({"error": "unknown dimension"}), 400
        return jsonify(rows)

    @app.route("/api/charts/<name>")
    def api_chart(name):
        builder = charts.CHARTS.get(name)
        if builder is None:
            abort(404)
        extra = {}
        if name in charts.TAKES_ROLE_FILTERS:
            extra = {"families": tuple(request.args.getlist("family")),
                     "levels": tuple(request.args.getlist("level"))}
        payload = builder(get_conn(), _sector_arg() or None, _window_arg(), **extra)
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

    @app.route("/health")
    def health_page():
        conn = get_conn()
        stats = conn.execute(
            "SELECT kind, COUNT(*) total, SUM(success) ok FROM emails GROUP BY kind").fetchall()
        return render_template(
            "health.html",
            companies=analytics.scraper_health(conn, {"pharma": list(SCRAPERS), "tech": list(TECH_SCRAPERS)}),
            runs={s: analytics.run_history(conn, s) for s in ("pharma", "tech")},
            stats=stats,
            claude=analytics.claude_usage(conn, date.today()),
        )

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", "5050")), debug=False)
