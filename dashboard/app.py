from __future__ import annotations

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

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5050, debug=True)
