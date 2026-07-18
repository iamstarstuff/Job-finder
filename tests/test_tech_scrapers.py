from jobfinder import tech_scrapers
from tests.conftest import FakeSession, FakeResponse


def test_matches_target_role_catches_real_variants():
    for title in [
        "Senior Software Engineer, Site Reliability Engineering, Cloud Storage",
        "Fraud Data Scientist",
        "ML Engineer",
        "BI Analyst",
        "Cloud Platform Engineer",
        "Splunk Administrator",
        "DevOps Engineer II",
        "Business Intelligence Analyst",
    ]:
        assert tech_scrapers.matches_target_role(title), title


def test_matches_target_role_excludes_noise_and_false_substrings():
    for title in [
        "Frontend Engineer (HTML/CSS)",  # must not match on "ml" inside "html"
        "Warehouse Supervisor",
        "Sales Compensation Administration Manager",
        "Responsible AI Program Manager",  # must not match on "bi" inside "Responsible"
        "Homes Advisor, Dundalk",
    ]:
        assert not tech_scrapers.matches_target_role(title), title


GOOGLE_PAGE1 = b"""<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:[["1001","Senior SRE, Cloud Storage","https://google.com/apply?jobId=1001"],["1002","Sales Rep","https://google.com/apply?jobId=1002"]]
, sideChannel: {}});</script>"""
GOOGLE_PAGE2 = b"""<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:[["1003","Data Scientist, Ads","https://google.com/apply?jobId=1003"],["1004","Warehouse Associate","https://google.com/apply?jobId=1004"]]
, sideChannel: {}});</script>"""


def test_google_paginates_filters_roles_and_stops_on_repeated_page():
    fake = FakeSession({
        "https://careers.google.com/jobs/results/?location=Ireland&page=1": FakeResponse(GOOGLE_PAGE1),
        "https://careers.google.com/jobs/results/?location=Ireland&page=2": FakeResponse(GOOGLE_PAGE2),
        # page 3 repeats page 2's content verbatim, simulating Google's real
        # behavior of clamping to the last valid page instead of returning empty
        "https://careers.google.com/jobs/results/?location=Ireland&page=3": FakeResponse(GOOGLE_PAGE2),
    })
    jobs = tech_scrapers.google(fake)
    assert [j.title for j in jobs] == ["Senior SRE, Cloud Storage", "Data Scientist, Ads"]
    assert jobs[0].sector == "tech"
    assert jobs[0].url == "https://google.com/apply?jobId=1001"
    assert jobs[0].company == "Google"


def test_google_returns_empty_when_no_data_chunk_found():
    fake = FakeSession({
        "https://careers.google.com/jobs/results/?location=Ireland&page=1": FakeResponse(b"<html>no data here</html>"),
    })
    assert tech_scrapers.google(fake) == []


AIB_PAGE_HTML = b"""
<span class="paginationLabel" aria-label="Results 1 - 2">Results <b>1 - 2</b> of <b>2</b></span>
<tr class="data-row"><td><a class="jobTitle-link" href="/aib/job/Dublin-Fraud-Data-Scientist-IE/1366746757/">Fraud Data Scientist</a></td></tr>
<tr class="data-row"><td><a class="jobTitle-link" href="/aib/job/Dublin-Homes-Advisor-IE/1366858457/">Homes Advisor, Dundalk</a></td></tr>
"""


def test_aib_filters_roles_and_builds_absolute_urls():
    fake = FakeSession({
        "https://jobs.aib.ie/aib/go/SearchAllJobs/9605800/?startrow=0": FakeResponse(AIB_PAGE_HTML),
    })
    jobs = tech_scrapers.aib(fake)
    assert len(jobs) == 1
    assert jobs[0].title == "Fraud Data Scientist"
    assert jobs[0].url == "https://jobs.aib.ie/aib/job/Dublin-Fraud-Data-Scientist-IE/1366746757/"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "AIB"
