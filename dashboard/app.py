from __future__ import annotations

import sys
from pathlib import Path

# allow running as a script: python dashboard/app.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, g, jsonify, render_template, request

from jobfinder import analytics, config, storage


def create_app(db_path=None) -> Flask:
    app = Flask(__name__)
    app.config["DB_PATH"] = str(db_path or config.DB_PATH)

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
        conn = get_conn()
        return render_template(
            "index.html",
            overview=analytics.overview(conn),
            per_company=analytics.jobs_per_company(conn),
            lifespans=analytics.median_days_active(conn),
        )

    @app.route("/jobs")
    def jobs():
        conn = get_conn()
        company = request.args.get("company", "")
        query = request.args.get("q", "")
        active = request.args.get("active", "")
        sql = "SELECT * FROM jobs WHERE 1=1"
        params = []
        if company:
            sql += " AND company = ?"
            params.append(company)
        if query:
            sql += " AND title LIKE ?"
            params.append(f"%{query}%")
        if active == "1":
            sql += " AND is_active = 1"
        sql += " ORDER BY first_seen DESC LIMIT 500"
        rows = conn.execute(sql, params).fetchall()
        companies = [r["company"] for r in conn.execute(
            "SELECT DISTINCT company FROM jobs ORDER BY company")]
        return render_template("jobs.html", jobs=rows, companies=companies,
                               company=company, q=query, active=active)

    @app.route("/api/jobs-per-company")
    def api_jobs_per_company():
        return jsonify(analytics.jobs_per_company(get_conn()))

    @app.route("/api/new-per-week")
    def api_new_per_week():
        return jsonify(analytics.new_jobs_per_week(get_conn()))

    @app.route("/api/categories")
    def api_categories():
        return jsonify(analytics.category_breakdown(get_conn()))

    @app.route("/api/top-skills")
    def api_top_skills():
        return jsonify(analytics.top_skills(get_conn()))

    @app.route("/api/seniority-breakdown")
    def api_seniority_breakdown():
        return jsonify(analytics.seniority_breakdown(get_conn()))

    @app.route("/api/skills-by-category")
    def api_skills_by_category():
        return jsonify(analytics.skills_by_category(get_conn()))

    @app.route("/api/drilldown/<dimension>")
    def api_drilldown(dimension):
        conn = get_conn()
        value = request.args.get("value", "")
        if dimension == "company":
            rows = conn.execute(
                """SELECT title, company, url, first_seen FROM jobs
                   WHERE company = ? ORDER BY first_seen DESC LIMIT 100""",
                (value,),
            ).fetchall()
        elif dimension == "skill":
            rows = conn.execute(
                """SELECT jobs.title, jobs.company, jobs.url, jobs.first_seen
                   FROM jobs
                   JOIN job_skills ON job_skills.job_id = jobs.id
                   JOIN skills ON skills.id = job_skills.skill_id
                   WHERE skills.name = ?
                   ORDER BY jobs.first_seen DESC LIMIT 100""",
                (value,),
            ).fetchall()
        elif dimension == "seniority":
            seniority_value = None if value == "Unspecified" else value
            rows = conn.execute(
                """SELECT jobs.title, jobs.company, jobs.url, jobs.first_seen
                   FROM jobs
                   JOIN job_details ON job_details.job_id = jobs.id
                   WHERE job_details.seniority IS ? AND job_details.enrichment_failed = 0
                   ORDER BY jobs.first_seen DESC LIMIT 100""",
                (seniority_value,),
            ).fetchall()
        elif dimension == "category":
            all_jobs = conn.execute(
                "SELECT title, company, url, first_seen FROM jobs ORDER BY first_seen DESC"
            ).fetchall()
            rows = [r for r in all_jobs if analytics.categorize(r["title"]) == value][:100]
        else:
            return jsonify({"error": "unknown dimension"}), 400
        return jsonify([
            {"title": r["title"], "company": r["company"], "url": r["url"], "first_seen": r["first_seen"]}
            for r in rows
        ])

    @app.route("/analytics")
    def analytics_page():
        return render_template("analytics.html")

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
        try:
            lines = config.LOG_PATH.read_text().splitlines()[-300:]
        except FileNotFoundError:
            lines = ["(no log file yet)"]
        return render_template("logs.html", lines=lines)

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5050, debug=True)
