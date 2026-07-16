from jobfinder import enrichment


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
