import enrich_jobs


def test_cli_default_is_a_normal_enrichment_run():
    assert enrich_jobs.parse_args([]).reextract is False


def test_cli_reextract_flag():
    assert enrich_jobs.parse_args(["--reextract"]).reextract is True
