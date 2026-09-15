import json

from jobfinder import enrichment
from jobfinder import storage
from jobfinder.models import Job
from tests.conftest import FakeSession, FakeResponse


LDJSON_HTML = """<html><head>
<script type="application/ld+json">
{"@type": "JobPosting", "title": "QC Analyst",
 "description": "<p>We need <strong>SAP</strong> and GMP experience.</p>"}
</script>
</head><body></body></html>"""

LDJSON_NON_JOBPOSTING = """<script type="application/ld+json">
{"@type": "Organization", "name": "Acme"}
</script>"""

LDJSON_MALFORMED = '<script type="application/ld+json">{not valid json}</script>'

LDJSON_NO_DESCRIPTION = """<script type="application/ld+json">
{"@type": "JobPosting", "title": "QC Analyst"}
</script>"""


def test_extract_ldjson_description_strips_html_tags():
    assert enrichment.extract_ldjson_description(LDJSON_HTML) == "We need SAP and GMP experience."


def test_extract_ldjson_description_returns_none_for_non_jobposting():
    assert enrichment.extract_ldjson_description(LDJSON_NON_JOBPOSTING) is None


def test_extract_ldjson_description_skips_malformed_json():
    assert enrichment.extract_ldjson_description(LDJSON_MALFORMED) is None


def test_extract_ldjson_description_returns_none_when_no_script_tag():
    assert enrichment.extract_ldjson_description("<html><body>No JSON-LD here.</body></html>") is None


def test_extract_ldjson_description_returns_none_when_description_missing():
    assert enrichment.extract_ldjson_description(LDJSON_NO_DESCRIPTION) is None


def test_extract_seniority_tiers():
    assert enrichment.extract_seniority("Senior Quality Investigation Engineer") == "Senior"
    assert enrichment.extract_seniority("Site Analytical Sciences Associate Principal Scientist") == "Lead"
    assert enrichment.extract_seniority("Director, Global Compound Market Access") == "Director"
    assert enrichment.extract_seniority("Graduate Programme - Manufacturing") == "Junior"
    assert enrichment.extract_seniority("Technology Engineer - SAP Supply Chain") is None


def test_extract_skills_matches_multiple_and_dedupes_category():
    desc = ("Adheres to Good Manufacturing Practices and Standard Operating Procedures. "
            "Uses SAP, Trackwise and Veeva Vault to manage batch records.")
    names = {name for name, _ in enrichment.extract_skills(desc)}
    assert names == {"GMP", "SOP", "SAP", "Trackwise", "Veeva Vault"}


def test_extract_skills_no_match_returns_empty_list():
    assert enrichment.extract_skills("A lovely day for a walk in the park.") == []


def test_extract_skills_returns_category_alongside_name():
    result = enrichment.extract_skills("Requires strong Python and SQL skills.")
    assert ("Python", "Software") in result
    assert ("SQL", "Software") in result


def test_extract_skills_bare_sap_does_not_match_asap():
    names = {name for name, _ in enrichment.extract_skills("We work ASAP on tasks")}
    assert "SAP" not in names


def test_extract_skills_matches_short_tokens_followed_by_punctuation():
    names = {name for name, _ in enrichment.extract_skills("Experience with GMP, SQL and Excel.")}
    assert {"GMP", "SQL", "Excel"} <= names


def test_extract_skills_matches_parenthesized_gmp():
    names = {name for name, _ in enrichment.extract_skills("Knowledge of (GMP) required")}
    assert "GMP" in names


def test_extract_skills_matches_slash_separated_tokens():
    names = {name for name, _ in enrichment.extract_skills("Skills: SQL/Python.")}
    assert {"SQL", "Python"} <= names


def test_extract_skills_excel_does_not_match_excellent():
    names = {name for name, _ in enrichment.extract_skills("Excellent communication skills required.")}
    assert "Excel" not in names


def test_extract_seniority_lead_does_not_match_misleading():
    assert enrichment.extract_seniority("Misleading Job Title Example") is None


def test_extract_seniority_intern_matches_inflections():
    assert enrichment.extract_seniority("Data Science Internship") == "Junior"
    assert enrichment.extract_seniority("Graduate Internship Programme") == "Junior"
    assert enrichment.extract_seniority("Summer Intern - Quality") == "Junior"
    assert enrichment.extract_seniority("Internships Available - R&D") == "Junior"


def test_extract_seniority_intern_does_not_match_unrelated_words():
    assert enrichment.extract_seniority("International Sales Manager") is None
    assert enrichment.extract_seniority("Internal Audit Manager") is None
    assert enrichment.extract_seniority("Internet Systems Analyst") is None


def test_extract_seniority_pre_existing_behaviors_unchanged():
    assert enrichment.extract_seniority("Senior Quality Investigation Engineer") == "Senior"
    assert enrichment.extract_seniority("Director, Global Compound Market Access") == "Director"
    assert enrichment.extract_seniority(
        "Site Analytical Sciences Associate Principal Scientist"
    ) == "Lead"
    assert enrichment.extract_seniority("Technology Engineer - SAP Supply Chain") is None


BMS_STYLE_HTML = ("<script type=\"application/ld+json\">"
                   '{"@type": "JobPosting", "description": '
                   '"Adheres to GMP and uses SAP and Trackwise."}'
                   "</script>").encode()


def test_fetch_description_parses_ldjson_from_response():
    session = FakeSession({"https://example.com/job/1": FakeResponse(content=BMS_STYLE_HTML)})
    result = enrichment.fetch_description(session, "https://example.com/job/1")
    assert result == "Adheres to GMP and uses SAP and Trackwise."


def test_fetch_description_returns_none_when_no_ldjson():
    session = FakeSession({"https://example.com/job/2": FakeResponse(content=b"<html>JS shell</html>")})
    assert enrichment.fetch_description(session, "https://example.com/job/2") is None


def test_run_enriches_new_jobs_and_isolates_failures(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "Senior SAP Engineer", "https://example.com/job/1", "https://example.com/careers"),
        Job("Abbvie", "Unreachable Job", "https://example.com/job/missing", "https://example.com/careers"),
        Job("Abbvie", "No JSON-LD Job", "https://example.com/job/no-ldjson", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")

    session = FakeSession({
        "https://example.com/job/1": FakeResponse(content=BMS_STYLE_HTML),
        "https://example.com/job/no-ldjson": FakeResponse(content=b"<html>JS shell</html>"),
        # job/missing intentionally has no route -> FakeSession returns 404
    })

    result = enrichment.run(conn, session, "2026-07-16T12:00:00")

    assert result.enriched == 1
    assert result.failed == 2

    def details_for(url):
        job_id = conn.execute("SELECT id FROM jobs WHERE url=?", (url,)).fetchone()["id"]
        return conn.execute("SELECT * FROM job_details WHERE job_id=?", (job_id,)).fetchone()

    ok = details_for("https://example.com/job/1")
    assert ok["enrichment_failed"] == 0
    assert ok["seniority"] == "Senior"

    unreachable = details_for("https://example.com/job/missing")
    assert unreachable["enrichment_failed"] == 1

    no_ldjson = details_for("https://example.com/job/no-ldjson")
    assert no_ldjson["enrichment_failed"] == 1


def test_run_enriches_a_newly_added_rollout_company(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Regeneron", [
        Job("Regeneron", "QC Technical Resources Specialist",
            "https://example.com/regeneron/1", "https://example.com/careers"),
    ], "2026-07-17T10:00:00")

    session = FakeSession({
        "https://example.com/regeneron/1": FakeResponse(content=BMS_STYLE_HTML),
    })

    result = enrichment.run(conn, session, "2026-07-17T12:00:00")

    assert result.enriched == 1
    assert result.failed == 0


def test_run_only_processes_scoped_companies(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://example.com/abbvie/1", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")
    storage.record_company_snapshot(conn, "Alkermes", [
        Job("Alkermes", "QC Analyst", "https://example.com/alkermes/1", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")

    session = FakeSession({
        "https://example.com/abbvie/1": FakeResponse(content=BMS_STYLE_HTML),
        # No route for alkermes/1 -- if run() ever requests it, FakeSession
        # returns a 404 stub rather than raising, so we must assert on
        # session.calls to prove the out-of-scope company was never touched.
    })

    result = enrichment.run(conn, session, "2026-07-16T12:00:00")

    assert result.enriched == 1
    assert result.failed == 0
    called_urls = {url for _, url, _ in session.calls}
    assert "https://example.com/alkermes/1" not in called_urls

    alkermes_job_id = conn.execute(
        "SELECT id FROM jobs WHERE url=?", ("https://example.com/alkermes/1",)
    ).fetchone()["id"]
    assert conn.execute(
        "SELECT COUNT(*) c FROM job_details WHERE job_id=?", (alkermes_job_id,)
    ).fetchone()["c"] == 0


AMGEN_SOLR_PAGE_1 = {
    "jobs": [
        {"guid": "AAAA0000AAAA0000AAAA0000AAAA0000",
         "description": "Wrong job, page 1 entry 1."},
        {"guid": "91F9C7D5EFFF4A1696A7370CB6EFB74A",
         "description": "Needs SAP and GMP experience for this role."},
    ],
    "pagination": {"total": 2, "has_more_pages": False},
}

AMGEN_SOLR_NO_MATCH = {
    "jobs": [
        {"guid": "AAAA0000AAAA0000AAAA0000AAAA0000", "description": "Not the target job."},
    ],
    "pagination": {"total": 1, "has_more_pages": False},
}


def test_fetch_amgen_description_matches_by_guid():
    session = FakeSession({
        "https://prod-search-api.jobsyn.org/api/v1/solr/search": FakeResponse(json_data=AMGEN_SOLR_PAGE_1),
    })
    url = "https://www.amgen.jobs/dublin-irl/some-role/91F9C7D5EFFF4A1696A7370CB6EFB74A/job/"
    assert enrichment.fetch_amgen_description(session, url) == "Needs SAP and GMP experience for this role."


def test_fetch_amgen_description_returns_none_when_guid_not_found():
    session = FakeSession({
        "https://prod-search-api.jobsyn.org/api/v1/solr/search": FakeResponse(json_data=AMGEN_SOLR_NO_MATCH),
    })
    url = "https://www.amgen.jobs/dublin-irl/some-role/91F9C7D5EFFF4A1696A7370CB6EFB74A/job/"
    assert enrichment.fetch_amgen_description(session, url) is None


def test_fetch_amgen_description_returns_none_for_unparseable_url():
    session = FakeSession({})
    assert enrichment.fetch_amgen_description(session, "https://www.amgen.jobs/not-a-job-url") is None
    assert session.calls == []  # no point calling the API without a guid to match


def test_run_dispatches_amgen_jobs_to_amgen_fetcher(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Amgen", [
        Job("Amgen", "Sr Associate Business Performance",
            "https://www.amgen.jobs/dublin-irl/some-role/91F9C7D5EFFF4A1696A7370CB6EFB74A/job/",
            "https://www.amgen.jobs/dublin-irl/"),
    ], "2026-07-17T10:00:00")

    # Deliberately no route for the job's own detail-page URL — if run()
    # ever fetched it directly (the generic JSON-LD path), FakeSession
    # would 404 and this test would fail with result.failed == 1.
    session = FakeSession({
        "https://prod-search-api.jobsyn.org/api/v1/solr/search": FakeResponse(json_data=AMGEN_SOLR_PAGE_1),
    })

    result = enrichment.run(conn, session, "2026-07-17T12:00:00")

    assert result.enriched == 1
    assert result.failed == 0


def test_run_skips_jobs_already_enriched(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "Abbvie", [
        Job("Abbvie", "SAP Engineer", "https://example.com/job/1", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")
    job_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://example.com/job/1",)).fetchone()["id"]
    storage.save_enrichment(conn, job_id, "Already done.", "Senior", [], "2026-07-16T10:30:00")

    session = FakeSession({})  # no routes registered — a call here would fail the test
    result = enrichment.run(conn, session, "2026-07-16T12:00:00")

    assert result.enriched == 0
    assert result.failed == 0
    assert session.calls == []


def test_extract_skills_matches_new_tech_keywords():
    desc = ("Requires strong Kubernetes and Terraform experience, plus AWS "
            "and Splunk. Familiarity with Airflow and dbt models a plus.")
    names = {name for name, _ in enrichment.extract_skills(desc)}
    assert {"Kubernetes", "Terraform", "AWS", "Splunk", "Airflow", "dbt"} <= names


def test_extract_skills_tech_keywords_avoid_false_positives():
    desc = "There are no flaws or laws being broken here, just JavaScript and a reaction."
    names = {name for name, _ in enrichment.extract_skills(desc)}
    assert "AWS" not in names
    assert "Java" not in names
    assert "React" not in names


def test_extract_skills_existing_pharma_keywords_still_work():
    desc = "Adheres to Good Manufacturing Practices and uses SAP daily."
    names = {name for name, _ in enrichment.extract_skills(desc)}
    assert {"GMP", "SAP"} <= names


def _google_entry(job_id, title, url, desc="", resp="", quals=""):
    entry = [None] * 21
    entry[0], entry[1], entry[2] = job_id, title, url
    entry[3] = [None, resp]
    entry[4] = [None, quals]
    entry[10] = [None, desc]
    return entry


def _google_page_html(entries, total):
    return ("<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:[" +
            json.dumps(entries) + f",null,{total},{len(entries)}]" +
            ", sideChannel: {}});</script>").encode()


def test_fetch_google_description_matches_by_url_and_combines_fields():
    entries = [
        _google_entry("1", "Senior SRE", "https://apply/1",
                       desc="<p>Main desc</p>", resp="<ul><li>Resp</li></ul>", quals="<ul><li>Quals</li></ul>"),
        _google_entry("2", "Sales Rep", "https://apply/2"),
    ]
    session = FakeSession({
        "https://careers.google.com/jobs/results/?location=Ireland&page=1":
            FakeResponse(_google_page_html(entries, total=2)),
    })
    result = enrichment.fetch_google_description(session, "https://apply/1")
    assert result == "Main desc Resp Quals"


def test_fetch_google_description_returns_none_when_no_match():
    entries = [_google_entry("1", "Senior SRE", "https://apply/1", desc="<p>Main desc</p>")]
    session = FakeSession({
        "https://careers.google.com/jobs/results/?location=Ireland&page=1":
            FakeResponse(_google_page_html(entries, total=1)),
    })
    assert enrichment.fetch_google_description(session, "https://apply/999") is None


def test_fetch_amazon_description_matches_by_url():
    session = FakeSession({
        "https://www.amazon.jobs/en/search.json": FakeResponse(json_data={
            "hits": 2,
            "jobs": [
                {"job_path": "/en/jobs/1/devops", "description": "Needs Kubernetes and Terraform."},
                {"job_path": "/en/jobs/2/retail", "description": "Retail job desc."},
            ],
        }),
    })
    result = enrichment.fetch_amazon_description(session, "https://www.amazon.jobs/en/jobs/1/devops")
    assert result == "Needs Kubernetes and Terraform."


def test_fetch_amazon_description_returns_none_when_no_match():
    session = FakeSession({
        "https://www.amazon.jobs/en/search.json": FakeResponse(json_data={
            "hits": 1,
            "jobs": [{"job_path": "/en/jobs/1/devops", "description": "Needs Kubernetes."}],
        }),
    })
    assert enrichment.fetch_amazon_description(session, "https://www.amazon.jobs/en/jobs/999/nope") is None


SUCCESSFACTORS_JOB_HTML = b'<html><body><div class="jobdescription"><p>Needs <strong>Splunk</strong> and Kubernetes.</p></div></body></html>'
SUCCESSFACTORS_NO_DESCRIPTION_HTML = b"<html><body>No description here.</body></html>"


def test_fetch_successfactors_description_extracts_text():
    session = FakeSession({"https://jobs.aib.ie/aib/job/1": FakeResponse(SUCCESSFACTORS_JOB_HTML)})
    result = enrichment.fetch_successfactors_description(session, "https://jobs.aib.ie/aib/job/1")
    assert result == "Needs Splunk and Kubernetes."


def test_fetch_successfactors_description_returns_none_when_class_absent():
    session = FakeSession({"https://careers.ey.com/ey/job/1": FakeResponse(SUCCESSFACTORS_NO_DESCRIPTION_HTML)})
    assert enrichment.fetch_successfactors_description(session, "https://careers.ey.com/ey/job/1") is None


def test_enrichment_companies_includes_ten_tech_companies():
    tech_companies = {
        "Mastercard", "Accenture", "Intel", "Citibank", "Microsoft",
        "Google", "Amazon", "AWS", "AIB", "EY",
    }
    assert tech_companies <= set(enrichment.ENRICHMENT_COMPANIES)
    assert "Allianz Partners" not in enrichment.ENRICHMENT_COMPANIES


STRIPE_JOB_HTML = b'<html><body><div class="ArticleMarkdown"><p>Needs <strong>SQL</strong> and Python.</p></div></body></html>'
STRIPE_NO_DESCRIPTION_HTML = b"<html><body>No description here.</body></html>"


def test_fetch_stripe_description_extracts_text():
    session = FakeSession({"https://stripe.com/jobs/listing/data-scientist/1": FakeResponse(STRIPE_JOB_HTML)})
    result = enrichment.fetch_stripe_description(session, "https://stripe.com/jobs/listing/data-scientist/1")
    assert result == "Needs SQL and Python."


def test_fetch_stripe_description_returns_none_when_class_absent():
    session = FakeSession({"https://stripe.com/jobs/listing/data-scientist/2": FakeResponse(STRIPE_NO_DESCRIPTION_HTML)})
    assert enrichment.fetch_stripe_description(session, "https://stripe.com/jobs/listing/data-scientist/2") is None


def test_fetch_jpmorganchase_description_matches_by_id():
    session = FakeSession({
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions": FakeResponse(json_data={
            "items": [{
                "TotalJobsCount": 2,
                "requisitionList": [
                    {"Id": "210708545", "ShortDescriptionStr": "Needs Databricks and SQL."},
                    {"Id": "210759082", "ShortDescriptionStr": "Needs React."},
                ],
            }],
        }),
    })
    result = enrichment.fetch_jpmorganchase_description(
        session, "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210708545",
    )
    assert result == "Needs Databricks and SQL."


def test_fetch_jpmorganchase_description_returns_none_when_no_match():
    session = FakeSession({
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions": FakeResponse(json_data={
            "items": [{
                "TotalJobsCount": 1,
                "requisitionList": [{"Id": "210708545", "ShortDescriptionStr": "Needs Databricks."}],
            }],
        }),
    })
    result = enrichment.fetch_jpmorganchase_description(
        session, "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/999999999",
    )
    assert result is None


def test_fetch_jpmorganchase_description_returns_none_for_unparseable_url():
    session = FakeSession({})
    assert enrichment.fetch_jpmorganchase_description(session, "https://example.com/not-a-job-url") is None


def test_enrichment_companies_includes_round5_companies():
    round5 = {"Stripe", "JPMorganChase", "Salesforce"}
    assert round5 <= set(enrichment.ENRICHMENT_COMPANIES)
    assert "Infosys" not in enrichment.ENRICHMENT_COMPANIES


def test_company_fetchers_includes_round5_dedicated_fetchers():
    assert enrichment.COMPANY_FETCHERS["Stripe"] is enrichment.fetch_stripe_description
    assert enrichment.COMPANY_FETCHERS["JPMorganChase"] is enrichment.fetch_jpmorganchase_description
    assert "Salesforce" not in enrichment.COMPANY_FETCHERS


def test_company_fetchers_routes_tech_companies_correctly():
    assert enrichment.COMPANY_FETCHERS["Google"] is enrichment.fetch_google_description
    assert enrichment.COMPANY_FETCHERS["Amazon"] is enrichment.fetch_amazon_description
    assert enrichment.COMPANY_FETCHERS["AWS"] is enrichment.fetch_amazon_description
    assert enrichment.COMPANY_FETCHERS["AIB"] is enrichment.fetch_successfactors_description
    assert enrichment.COMPANY_FETCHERS["EY"] is enrichment.fetch_successfactors_description
    # Mastercard/Accenture/Intel/Citibank/Microsoft deliberately have no
    # entry here -- they fall through to the generic fetch_description
    # via COMPANY_FETCHERS.get(company, fetch_description) in run().
    assert "Mastercard" not in enrichment.COMPANY_FETCHERS


def test_extract_skills_spark_ignores_the_english_word():
    # MSD's boilerplate "the spark that fuels innovation" appeared in 160
    # job descriptions and made Spark the #3 skill overall. Only the
    # product names should count.
    assert ("Spark", "Data Engineering") not in enrichment.extract_skills(
        "The difference between potential and achievement lies in the spark that fuels innovation."
    )
    assert ("Spark", "Data Engineering") in enrichment.extract_skills("Experience with Apache Spark required.")
    assert ("Spark", "Data Engineering") in enrichment.extract_skills("Build pipelines in PySpark and Airflow.")


def test_astellas_is_enriched_via_successfactors_fetcher():
    # careers.astellas.com job pages render the description in
    # class="jobdescription" (confirmed live 2026-09-15), exactly like AIB/EY.
    assert "Astellas" in enrichment.ENRICHMENT_COMPANIES
    assert enrichment.COMPANY_FETCHERS["Astellas"] is enrichment.fetch_successfactors_description


def test_reextract_skills_rebuilds_links_from_current_vocabulary(tmp_path):
    conn = storage.connect(tmp_path / "t.db")
    storage.record_company_snapshot(conn, "MSD", [
        Job("MSD", "Engineer", "https://example.com/msd/1", "https://example.com/careers"),
        Job("MSD", "Broken", "https://example.com/msd/2", "https://example.com/careers"),
    ], "2026-07-16T10:00:00")
    ok_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://example.com/msd/1",)).fetchone()["id"]
    bad_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://example.com/msd/2",)).fetchone()["id"]
    # Saved under the old vocabulary: a bogus Spark link, and no GMP link
    # even though the text plainly says GMP.
    storage.save_enrichment(conn, ok_id, "the spark that fuels innovation; GMP experience required",
                            "Senior", [("Spark", "Data Engineering")], "2026-07-16T11:00:00")
    storage.save_enrichment(conn, bad_id, "", None, [], "2026-07-16T11:00:00", failed=True)

    reprocessed = enrichment.reextract_skills(conn)

    assert reprocessed == 1  # failed rows have no description and are skipped
    names = {r["name"] for r in conn.execute(
        "SELECT skills.name FROM job_skills JOIN skills ON skills.id = job_skills.skill_id WHERE job_id = ?", (ok_id,))}
    assert names == {"GMP"}
    assert conn.execute("SELECT seniority FROM job_details WHERE job_id=?", (ok_id,)).fetchone()["seniority"] == "Senior"
