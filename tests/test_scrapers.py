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
        "https://jobs.bms.com/api/apply/v2/jobs": FakeResponse(json_data={
            "count": 1,
            "positions": [{"name": "Associate Director QA",
                           "canonicalPositionUrl": "https://jobs.bms.com/careers/job/1"}],
        }),
    })
    jobs = scrapers.bms(fake)
    assert jobs[0].title == "Associate Director QA"
    assert jobs[0].url == "https://jobs.bms.com/careers/job/1"


def test_msd_parses_phenom_api():
    fake = FakeSession({
        "https://jobs.msd.com/widgets": FakeResponse(json_data={
            "refineSearch": {"totalHits": 1, "data": {"jobs": [
                {"title": "Bioprocess Engineer",
                 "applyUrl": "https://jobs.msd.com/job/123"},
            ]}},
        }),
    })
    jobs = scrapers.msd(fake)
    assert jobs[0].title == "Bioprocess Engineer"
    assert jobs[0].url == "https://jobs.msd.com/job/123"


def test_bms_and_msd_in_registry():
    assert "MSD" in scrapers.SCRAPERS
    # BMS is implemented but deliberately excluded from the registry: the live
    # Eightfold API rejects non-browser sessions (401/403 "Not authorized for
    # PCSX"). See .superpowers/sdd/task-8-report.md.
    assert "BMS" not in scrapers.SCRAPERS
