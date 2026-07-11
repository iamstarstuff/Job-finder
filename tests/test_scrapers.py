from jobfinder import scrapers
from tests.conftest import FakeSession, FakeResponse

APC_HTML = b"""<table>
<tr><th>Title</th><th>Closing</th></tr>
<tr><td class="title title--quaternary">QC Analyst</td>
    <td class="title title--senary">2026-08-01</td>
    <td><a href="https://approcess.com/jobs/qc">Apply</a></td></tr>
</table>"""

ABBVIE_HTML = b"""<div>
<a class="attrax-vacancy-tile__title" href="/en/job/warehouse-1">Warehouse Supervisor</a>
</div>"""

AZ_PAGE1 = b'<a class="search-results-link" href="/job/az-1">QA Specialist\nDublin</a>'
AZ_EMPTY = b"<div>no results</div>"

TAKEDA_HTML = b'<a data-job-id="1" href="job/tak-1"><h2 class="title">Process Lead</h2></a>'

def _amgen_response(jobs, total, page, total_pages):
    return FakeResponse(json_data={
        "jobs": jobs,
        "pagination": {
            "has_more_pages": page < total_pages,
            "offset": (page - 1) * 10,
            "page": page,
            "page_size": 10,
            "total": total,
            "total_pages": total_pages,
        },
    })


AMGEN_JOB1 = {
    "title_exact": "Engineer I", "title_slug": "engineer-i",
    "guid": "GUID1", "location_exact": "Dublin, IRL",
}
AMGEN_JOB2 = {
    "title_exact": "Engineer II", "title_slug": "engineer-ii",
    "guid": "GUID2", "location_exact": "Cork, IRL",
}

VLE_HTML = b"""<div class="table-content">
<p class="job-description">Scientist</p>
<a class="careers-link" href="/apply/1">Apply</a>
</div>"""

ASTELLAS_PAGE1 = b'<h3 class="article__header__text__title"><a href="/careers/j1">Director QA</a></h3>'
ASTELLAS_EMPTY = b"<div></div>"


def test_apc_parses_jobs():
    fake = FakeSession({"https://approcess.com/careers": FakeResponse(APC_HTML)})
    jobs = scrapers.apc(fake)
    assert jobs[0].title == "QC Analyst"
    assert jobs[0].url == "https://approcess.com/jobs/qc"
    assert jobs[0].closing_date == "2026-08-01"


def test_abbvie_builds_absolute_url():
    fake = FakeSession({"https://careers.abbvie.com": FakeResponse(ABBVIE_HTML)})
    jobs = scrapers.abbvie(fake)
    assert jobs[0].url == "https://careers.abbvie.com/en/job/warehouse-1"


def test_astrazeneca_paginates_until_empty():
    fake = FakeSession({
        "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2/1": FakeResponse(AZ_PAGE1),
        "https://careers.astrazeneca.com/location/ireland-jobs/7684/2963597/2/2": FakeResponse(AZ_EMPTY),
    })
    jobs = scrapers.astrazeneca(fake)
    assert len(jobs) == 1
    assert jobs[0].title == "QA Specialist"


def test_takeda():
    fake = FakeSession({"https://jobs.takeda.com": FakeResponse(TAKEDA_HTML)})
    jobs = scrapers.takeda(fake)
    assert jobs[0].url == "https://jobs.takeda.com/job/tak-1"


def test_amgen_parses_and_paginates_jobsyn_api():
    responses = iter([
        _amgen_response([AMGEN_JOB1], total=2, page=1, total_pages=2),
        _amgen_response([AMGEN_JOB2], total=2, page=2, total_pages=2),
    ])

    class Seq:
        calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return next(responses)

    session = Seq()
    jobs = scrapers.amgen(session)
    assert [j.title for j in jobs] == ["Engineer I", "Engineer II"]
    assert jobs[0].url == (
        "https://www.amgen.jobs/dublin-irl/engineer-i/GUID1/job/"
    )
    assert jobs[1].url == (
        "https://www.amgen.jobs/cork-irl/engineer-ii/GUID2/job/"
    )
    assert jobs[0].portal_url == scrapers.URLS["Amgen"]
    # X-Origin header required by the jobsyn API (400 without it, live-verified)
    assert session.calls[0][1]["headers"]["X-Origin"] == "www.amgen.jobs"
    assert session.calls[0][1]["params"]["page"] == 1
    assert session.calls[1][1]["params"]["page"] == 2


def test_amgen_stops_on_empty_batch():
    fake = FakeSession({
        "https://prod-search-api.jobsyn.org/api/v1/solr/search": FakeResponse(
            json_data={
                "jobs": [],
                "pagination": {
                    "has_more_pages": False, "offset": 0, "page": 1,
                    "page_size": 10, "total": 0, "total_pages": 0,
                },
            }
        ),
    })
    jobs = scrapers.amgen(fake)
    assert jobs == []


def test_vle():
    fake = FakeSession({"https://www.vletherapeutics.com/careers": FakeResponse(VLE_HTML)})
    jobs = scrapers.vle(fake)
    assert jobs[0].title == "Scientist"
    assert jobs[0].url == "https://www.vletherapeutics.com/apply/1"
    assert jobs[0].closing_date is None or jobs[0].closing_date == "N/A"


def test_astellas_paginates_by_offset():
    base = "https://astellas.avature.net/en_GB/careers/SearchJobs/?1329=%5B180801%5D&1329_format=1348&listFilterMode=1&jobOffset="
    fake = FakeSession({base + "0": FakeResponse(ASTELLAS_PAGE1),
                        base + "10": FakeResponse(ASTELLAS_EMPTY)})
    jobs = scrapers.astellas(fake)
    assert jobs[0].title == "Director QA"
    assert jobs[0].url == "https://astellas.avature.net/careers/j1"


def test_registry_contains_all_companies():
    assert set(scrapers.SCRAPERS) >= {
        "APC", "Abbvie", "Astrazeneca", "Takeda", "Amgen",
        "Vle therapeutics", "Astellas",
    }


def test_scrapers_do_not_swallow_errors():
    fake = FakeSession({})  # everything 404s
    try:
        scrapers.apc(fake)
        assert False, "should raise"
    except Exception:
        pass


def _wd_response(postings, total):
    return FakeResponse(json_data={"total": total, "jobPostings": postings})


def test_pfizer_parses_and_paginates_workday_api():
    page1 = [{"title": "Senior Scientist", "externalPath": "/job/Dublin/Senior-Scientist_1"}]
    page2 = [{"title": "QA Manager", "externalPath": "/job/Cork/QA-Manager_2"}]
    responses = iter([_wd_response(page1, 2), _wd_response(page2, 2)])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.pfizer(Seq())
    assert [j.title for j in jobs] == ["Senior Scientist", "QA Manager"]
    assert jobs[0].url == (
        "https://pfizer.wd1.myworkdayjobs.com/en-US/PfizerCareers"
        "/job/Dublin/Senior-Scientist_1"
    )


def test_pfizer_in_registry():
    assert "Pfizer" in scrapers.SCRAPERS


def test_bms_parses_eightfold_api():
    fake = FakeSession({
        "https://jobs.bms.com/api/pcsx/search": FakeResponse(json_data={
            "status": 200,
            "data": {
                "count": 1,
                "positions": [{"name": "Associate Director QA",
                               "positionUrl": "/careers/job/1"}],
            },
        }),
    })
    jobs = scrapers.bms(fake)
    assert jobs[0].title == "Associate Director QA"
    # relative positionUrl made absolute
    assert jobs[0].url == "https://jobs.bms.com/careers/job/1"


def test_msd_parses_phenom_api():
    fake = FakeSession({
        "https://jobs.msd.com/widgets": FakeResponse(json_data={
            "refineSearch": {"totalHits": 2, "data": {"jobs": [
                {"title": "Bioprocess Engineer",
                 "applyUrl": "https://jobs.msd.com/job/123/apply"},
                {"title": "QA Specialist",
                 "applyUrl": "https://jobs.msd.com/job/456"},
            ]}},
        }),
    })
    jobs = scrapers.msd(fake)
    assert jobs[0].title == "Bioprocess Engineer"
    # /apply suffix stripped so the link lands on the listing page
    assert jobs[0].url == "https://jobs.msd.com/job/123"
    assert jobs[1].url == "https://jobs.msd.com/job/456"


def test_bms_and_msd_in_registry():
    assert {"BMS", "MSD"} <= set(scrapers.SCRAPERS)


def test_gilead_parses_and_paginates_workday_api():
    page1 = [{"title": "Director, Supply Chain",
              "externalPath": "/job/Ireland---Cork/Director--Supply-Chain_R0052735-1"}]
    page2 = [{"title": "Senior Manager, Master Data Governance",
              "externalPath": "/job/Ireland---Cork/Senior-Manager--Master-Data-Governance_R0047916"}]
    responses = iter([_wd_response(page1, 2), _wd_response(page2, 2)])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.gilead(Seq())
    assert [j.title for j in jobs] == ["Director, Supply Chain", "Senior Manager, Master Data Governance"]
    assert jobs[0].url == (
        "https://gilead.wd1.myworkdayjobs.com/en-US/gileadcareers"
        "/job/Ireland---Cork/Director--Supply-Chain_R0052735-1"
    )


def test_gilead_in_registry():
    assert "Gilead" in scrapers.SCRAPERS


JAZZ_PAGE1 = b"""<ul class="results-content" id="job-list-section">
<li>
    <a href="/job/1457/associate-director-financial-planning-performance-finance-ie-dublin-dublin/" rel="nofollow">
        <h3>Associate Director, Financial Planning &amp; Performance</h3>
    </a>
</li>
</ul>
<div class="pagination">
<a href="?page_jobs=2" class="next">next &rsaquo;&rsaquo;</a>
</div>"""

JAZZ_PAGE2 = b"""<ul class="results-content" id="job-list-section">
<li>
    <a href="/job/1502/senior-scientist-analytical-ie-athlone/" rel="nofollow">
        <h3>Senior Scientist, Analytical</h3>
    </a>
</li>
</ul>"""


def test_jazz_paginates_until_no_next_link():
    # Longer/more specific route listed first: FakeSession._lookup matches by
    # prefix, and the page-1 URL is itself a prefix of the page-2 URL.
    fake = FakeSession({
        "https://careers.jazzpharma.com/jobs/ie/?page_jobs=2": FakeResponse(JAZZ_PAGE2),
        "https://careers.jazzpharma.com/jobs/ie/": FakeResponse(JAZZ_PAGE1),
    })
    jobs = scrapers.jazz(fake)
    assert [j.title for j in jobs] == [
        "Associate Director, Financial Planning & Performance",
        "Senior Scientist, Analytical",
    ]
    assert jobs[0].url == (
        "https://careers.jazzpharma.com/job/1457/"
        "associate-director-financial-planning-performance-finance-ie-dublin-dublin/"
    )
    assert jobs[0].portal_url == scrapers.URLS["Jazz Pharmaceuticals"]


def test_jazz_in_registry():
    assert "Jazz Pharmaceuticals" in scrapers.SCRAPERS


def _thermo_response(jobs, total_hits):
    return FakeResponse(json_data={
        "refineSearch": {"status": 200, "hits": len(jobs), "totalHits": total_hits,
                          "data": {"jobs": jobs}},
    })


def test_thermo_fisher_parses_phenom_api_and_strips_apply_suffix():
    job1 = {"title": "Scientist III (LCMS Pharma)",
            "applyUrl": "https://thermofisher.wd5.myworkdayjobs.com/ThermoFisherCareers"
                        "/job/Athlone-Ireland/Scientist-III--LCMS-Pharma-_R-01328306/apply"}
    job2 = {"title": "Material Handler II",
            "applyUrl": "https://thermofisher.wd5.myworkdayjobs.com/ThermoFisherCareers"
                        "/job/Athlone-Ireland/Material-Handler-II_R-01360000"}
    fake = FakeSession({"https://jobs.thermofisher.com/widgets": _thermo_response([job1, job2], 2)})
    jobs = scrapers.thermo_fisher(fake)
    assert [j.title for j in jobs] == ["Scientist III (LCMS Pharma)", "Material Handler II"]
    assert jobs[0].url == (
        "https://thermofisher.wd5.myworkdayjobs.com/ThermoFisherCareers"
        "/job/Athlone-Ireland/Scientist-III--LCMS-Pharma-_R-01328306"
    )
    assert jobs[1].url == (
        "https://thermofisher.wd5.myworkdayjobs.com/ThermoFisherCareers"
        "/job/Athlone-Ireland/Material-Handler-II_R-01360000"
    )


def test_thermo_fisher_paginates_by_offset():
    responses = iter([
        _thermo_response([{"title": "Scientist I", "applyUrl": "https://jobs.thermofisher.com/job/1/apply"}], 2),
        _thermo_response([{"title": "Scientist II", "applyUrl": "https://jobs.thermofisher.com/job/2/apply"}], 2),
    ])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.thermo_fisher(Seq())
    assert [j.title for j in jobs] == ["Scientist I", "Scientist II"]


def test_thermo_fisher_in_registry():
    assert "Thermo Fisher" in scrapers.SCRAPERS


JNJ_PAGE1 = b"""<section id="results">
<h2 class="job-count">Displaying <strong>1</strong> to <strong>1</strong> of <strong>2</strong> matching jobs</h2>
<ul class="PageList-items" id="js-job-search-results" data-results="2">
<li class="PageList-items-item card-job" data-id="r-087474">
    <div class="PagePromo">
        <div class="PagePromo-content">
            <h3 class="PagePromo-title">
                <a class="stretched-link Link js-view-job" href="/en/jobs/r-087474/director-surgical-vision/">Director, Surgical Vision Equipment Portfolio</a>
            </h3>
            <address class="PagePromo-location">Dublin Ireland</address>
        </div>
    </div>
</li>
</ul>
<nav aria-label="Pagination">
<ul class="pagination"><li class="page-item next"><a aria-label="Next page" class="page-link" href="https://www.careers.jnj.com/en/jobs/?page=2&amp;country=Ireland#results" rel="next nofollow">2</a></li></ul>
</nav>
</section>"""

JNJ_PAGE2 = b"""<section id="results">
<ul class="PageList-items" id="js-job-search-results" data-results="2">
<li class="PageList-items-item card-job" data-id="r-083581">
    <div class="PagePromo">
        <div class="PagePromo-content">
            <h3 class="PagePromo-title">
                <a class="stretched-link Link js-view-job" href="/en/jobs/r-083581/senior-manager-ra/">Senior Manager, RA &amp; R&amp;D Data Office</a>
            </h3>
            <address class="PagePromo-location">Cork Ireland</address>
        </div>
    </div>
</li>
</ul>
<nav aria-label="Pagination">
<ul class="pagination"><li class="disabled next page-item"><span class="page-link">2</span></li></ul>
</nav>
</section>"""


def test_jnj_paginates_server_rendered_search():
    # More-specific route (page=2) listed first: FakeSession._lookup matches
    # by prefix, and neither URL is a prefix of the other here since the
    # query strings diverge at "page=2" vs "country=Ireland" -- but keep the
    # brief's convention anyway for consistency with the other fixtures.
    fake = FakeSession({
        "https://www.careers.jnj.com/en/jobs/?page=2&country=Ireland": FakeResponse(JNJ_PAGE2),
        "https://www.careers.jnj.com/en/jobs/?country=Ireland": FakeResponse(JNJ_PAGE1),
    })
    jobs = scrapers.johnson_and_johnson(fake)
    assert [j.title for j in jobs] == [
        "Director, Surgical Vision Equipment Portfolio",
        "Senior Manager, RA & R&D Data Office",
    ]
    assert jobs[0].url == "https://www.careers.jnj.com/en/jobs/r-087474/director-surgical-vision/"
    assert jobs[0].portal_url == scrapers.JNJ_URL


def test_jnj_in_registry():
    assert "Johnson & Johnson" in scrapers.SCRAPERS


def test_regeneron_parses_and_paginates_workday_api():
    page1 = [{"title": "QC Analyst HPLC", "externalPath": "/job/Limerick/QC-Analyst-HPLC_R49031"}]
    page2 = [{"title": "Associate Director, Commercial Launch",
              "externalPath": "/job/Dublin/Associate-Director--Commercial-Launch_R47535"}]
    responses = iter([_wd_response(page1, 2), _wd_response(page2, 2)])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.regeneron(Seq())
    assert [j.title for j in jobs] == ["QC Analyst HPLC", "Associate Director, Commercial Launch"]
    assert jobs[0].url == (
        "https://regeneron.wd1.myworkdayjobs.com/en-US/Careers"
        "/job/Limerick/QC-Analyst-HPLC_R49031"
    )


def test_regeneron_in_registry():
    assert "Regeneron" in scrapers.SCRAPERS


def test_gsk_parses_and_paginates_workday_api():
    page1 = [{"title": "EHS Business Partner", "externalPath": "/job/Ireland---Dungarvan/EHS-Business-Partner_545675-1"}]
    page2 = [{"title": "CAPEX Manager", "externalPath": "/job/Ireland---Dungarvan/CAPEX-Manager_544110-1"}]
    responses = iter([_wd_response(page1, 2), _wd_response(page2, 2)])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.gsk(Seq())
    assert [j.title for j in jobs] == ["EHS Business Partner", "CAPEX Manager"]
    assert jobs[0].url == (
        "https://gsknch.wd3.myworkdayjobs.com/en-US/GSKCareers"
        "/job/Ireland---Dungarvan/EHS-Business-Partner_545675-1"
    )


def test_gsk_in_registry():
    assert "GSK" in scrapers.SCRAPERS
