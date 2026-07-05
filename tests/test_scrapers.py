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

AMGEN_PAGE1 = b"""<h4><a href="/irl/jobs/j1">Engineer I</a></h4>
<a class="next" href="/irl/jobs/?page=2">Next</a>"""
AMGEN_PAGE2 = b"<h4><a href='/irl/jobs/j2'>Engineer II</a></h4>"

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


def test_amgen_follows_next_link():
    fake = FakeSession({
        "https://www.amgen.jobs/irl/jobs/?page=2": FakeResponse(AMGEN_PAGE2),
        "https://www.amgen.jobs/irl/jobs/": FakeResponse(AMGEN_PAGE1),
    })
    jobs = scrapers.amgen(fake)
    assert [j.title for j in jobs] == ["Engineer I", "Engineer II"]


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
