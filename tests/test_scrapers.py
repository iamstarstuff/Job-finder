import pytest

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


# Trimmed from careers.jazzpharma.com's Radancy TalentBrew location page
# (live, 2026-11-21). The link nests the location inside itself, and every
# page also shows a "featured jobs" widget of US roles outside the results.
JAZZ_FEATURED = b"""<ul class="job-list__list"><li class="job-list__item"><h3 class="job-list__job-title">
<a class="job-list__job-link" data-job-id="103574233712"
   href="/job/philadelphia/director-medical-affairs-activation-lead/50396/103574233712">
   Director, Medical Affairs Activation Lead </a></h3></li></ul>"""

JAZZ_PAGE1 = b"""<section id="search-results">
<ul id="search-results-jobs" class="search-results-list__list" data-results-count="2">
<li class="search-results-list__item"><h2 class="search-results-list__job-title">
<a class="search-results-list__job-link" data-job-id="102804553744"
   href="/job/dublin/fp-and-a-data-and-analytics-manager/50396/102804553744">FP&amp;A Data &amp; Analytics Manager
   <span class="search-results-list__job-info-list"><span class="search-results-list__job-info job-location">
   <span><strong>Location: </strong>Dublin, Leinster [Full time]</span></span></span></a></h2></li>
<li class="search-results-list__item"><h2 class="search-results-list__job-title">
<a class="search-results-list__job-link" data-job-id="103519380288"
   href="/job/london/director-ethics-and-compliance-business-partner-eur-intl/50396/103519380288">Director, Ethics and  Compliance Business Partner, Eur/Intl
   <span class="search-results-list__job-info-list"><span class="search-results-list__job-info job-location">
   <span><strong>Location: </strong>London, England [Full time]</span></span></span></a></h2></li>
</ul></section>""" + JAZZ_FEATURED

JAZZ_PAGE2 = b"""<section id="search-results"><ul id="search-results-jobs" data-results-count="2"></ul>
</section>""" + JAZZ_FEATURED


def test_jazz_reads_talentbrew_ireland_results_and_skips_featured_jobs():
    # Jazz moved to Radancy TalentBrew on 2026-11-19 (/jobs/ie/ now
    # redirects to the homepage). Its Ireland location page lists the
    # roles; the featured-jobs widget repeats US roles on every page.
    base = "https://careers.jazzpharma.com/location/ireland-jobs/50396/2963597/2"
    fake = FakeSession({
        base + "/2": FakeResponse(JAZZ_PAGE2),
        base + "/1": FakeResponse(JAZZ_PAGE1),
    })
    jobs = scrapers.jazz(fake)
    assert [j.title for j in jobs] == [
        "FP&A Data & Analytics Manager",
        "Director, Ethics and Compliance Business Partner, Eur/Intl",
    ]
    assert jobs[0].url == (
        "https://careers.jazzpharma.com/job/dublin/fp-and-a-data-and-analytics-manager/50396/102804553744"
    )
    assert jobs[0].company == "Jazz Pharmaceuticals"
    assert jobs[0].portal_url == scrapers.URLS["Jazz Pharmaceuticals"] == base
    assert [c[1] for c in fake.calls] == [base + "/1", base + "/2"]


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


def _alkermes_response(reqs, total):
    return FakeResponse(json_data={"items": [{
        "TotalJobsCount": total,
        "requisitionList": reqs,
    }]})


def test_alkermes_parses_and_paginates_oracle_recruiting_cloud_api():
    responses = iter([
        _alkermes_response(
            [{"Id": "13992", "Title": "Lead, GMP Auditor"},
             {"Id": "13993", "Title": "Sr Financial Analyst"}],
            total=3,
        ),
        _alkermes_response([{"Id": "14001", "Title": "QA Specialist"}], total=3),
    ])

    class Seq:
        calls = []
        def get(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.alkermes(Seq())
    assert [j.title for j in jobs] == ["Lead, GMP Auditor", "Sr Financial Analyst", "QA Specialist"]
    assert jobs[0].url == (
        "https://hbap.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/13992"
    )
    assert jobs[0].portal_url == scrapers.ALKERMES_PORTAL


def test_alkermes_in_registry():
    assert "Alkermes" in scrapers.SCRAPERS


def _teva_response(positions, count):
    return FakeResponse(json_data={"positions": positions, "count": count})


def test_teva_parses_and_paginates_eightfold_api():
    responses = iter([
        _teva_response(
            [{"name": "Associate Director Global Quality Compliance TORCH",
              "canonicalPositionUrl": "https://www.careers.teva/careers/job/563602812978494"}],
            count=2,
        ),
        _teva_response(
            [{"name": "Site Microbiologist",
              "canonicalPositionUrl": "https://www.careers.teva/careers/job/563602812102826"}],
            count=2,
        ),
    ])

    class Seq:
        calls = []
        def get(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    session = Seq()
    jobs = scrapers.teva(session)
    assert [j.title for j in jobs] == [
        "Associate Director Global Quality Compliance TORCH", "Site Microbiologist",
    ]
    assert jobs[0].url == "https://www.careers.teva/careers/job/563602812978494"
    assert session.calls[0]["params"]["location"] == "Ireland"


def test_teva_falls_back_to_id_based_url_when_canonical_missing():
    # Some positions omit canonicalPositionUrl (or it's blank); the scraper
    # should build the URL from the position's numeric "id" instead of
    # dropping the job or emitting an empty link.
    responses = iter([
        _teva_response(
            [{"name": "Site Microbiologist", "id": 563602812102826, "canonicalPositionUrl": ""}],
            count=1,
        ),
    ])

    class Seq:
        calls = []
        def get(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    jobs = scrapers.teva(Seq())
    assert jobs[0].url == "https://www.careers.teva/careers/job/563602812102826"


def test_teva_in_registry():
    assert "Teva" in scrapers.SCRAPERS


def test_viatris_parses_and_paginates_workday_api_with_country_facet():
    # This tenant's "total" is only trustworthy on page 1 -- page 2 reports
    # total=0 live even though postings keep coming. A naive implementation
    # that re-reads "total" on every page would take page 2's bogus total=0
    # at face value and stop after page 2 (offset=2 >= total=0), silently
    # dropping page 3. Only the cached first-page total (3) correctly keeps
    # the loop going through all 3 pages/jobs.
    page1 = [{"title": "Manufacturing Operator",
              "externalPath": "/job/Damastown-Dublin-Ireland/Manufacturing-Operator_R5671425"}]
    page2 = [{"title": "Director Global Regulatory Compliance",
              "externalPath": "/job/Northern-Cross-Dublin-Ireland/Director-Regulatory-Compliance_R5665632"}]
    page3 = [{"title": "Head of External Sterile Operations",
              "externalPath": "/job/Anywhere-Europe/Head-of-External-Sterile-Operations_R5680119"}]
    responses = iter([_wd_response(page1, 3), _wd_response(page2, 0), _wd_response(page3, 3)])

    class Seq:
        calls = []
        def post(self, url, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    session = Seq()
    jobs = scrapers.viatris(session)
    assert [j.title for j in jobs] == [
        "Manufacturing Operator",
        "Director Global Regulatory Compliance",
        "Head of External Sterile Operations",
    ]
    assert jobs[0].url == (
        "https://viatris.wd5.myworkdayjobs.com/en-US/External"
        "/job/Damastown-Dublin-Ireland/Manufacturing-Operator_R5671425"
    )
    # tenant-specific facet key is "Country", not "Location_Country" (verified live)
    assert session.calls[0]["json"]["appliedFacets"] == {"Country": ["04a05835925f45b3a59406a2a6b72c8a"]}


def test_viatris_in_registry():
    assert "Viatris" in scrapers.SCRAPERS


GRIFOLS_PAGE1 = b"""<span class="paginationLabel">Results <b>1 \xe2\x80\x93 2</b> of <b>3</b></span>
<table>
<tbody>
<tr class="data-row">
    <td class="colTitle"><span class="jobTitle hidden-phone">
        <a href="/job/Dublin-Site-Procurement-Senior-Specialist/1393405333/" class="jobTitle-link">Site Procurement Senior Specialist</a>
    </span></td>
</tr>
<tr class="data-row">
    <td class="colTitle"><span class="jobTitle hidden-phone">
        <a href="/job/Dublin-Calibration-Engineer/1395411333/" class="jobTitle-link">Calibration Engineer</a>
    </span></td>
</tr>
</tbody>
</table>"""

GRIFOLS_PAGE2 = b"""<span class="paginationLabel">Results <b>3 \xe2\x80\x93 3</b> of <b>3</b></span>
<table>
<tbody>
<tr class="data-row">
    <td class="colTitle"><span class="jobTitle hidden-phone">
        <a href="/job/Dublin-Clinical-Research-Associate/1387026233/" class="jobTitle-link">Clinical Research Associate</a>
    </span></td>
</tr>
</tbody>
</table>"""


def test_grifols_paginates_successfactors_job2web_site():
    fake = FakeSession({
        scrapers.GRIFOLS_SEARCH + "2": FakeResponse(GRIFOLS_PAGE2),
        scrapers.GRIFOLS_SEARCH + "0": FakeResponse(GRIFOLS_PAGE1),
    })
    jobs = scrapers.grifols(fake)
    assert [j.title for j in jobs] == [
        "Site Procurement Senior Specialist", "Calibration Engineer", "Clinical Research Associate",
    ]
    assert jobs[0].url == "https://jobsearch.grifols.com/job/Dublin-Site-Procurement-Senior-Specialist/1393405333/"
    assert jobs[0].portal_url == scrapers.GRIFOLS_PORTAL


def test_grifols_in_registry():
    assert "Grifols" in scrapers.SCRAPERS


GRIFOLS_PAGE2_FILTER_DROPPED = b"""<span class="paginationLabel">Results <b>1 \xe2\x80\x93 1</b> of <b>500</b></span>
<table>
<tbody>
<tr class="data-row">
    <td class="colTitle"><span class="jobTitle hidden-phone">
        <a href="/job/Unrelated-Default-Listing/9999999/" class="jobTitle-link">Unrelated Default Listing</a>
    </span></td>
</tr>
</tbody>
</table>"""


def test_grifols_raises_when_pagination_range_shrinks_mid_run():
    # If the server drops the location filter mid-run, the results table
    # reverts to an unfiltered/default listing whose paginationLabel range
    # ("1 - 1 of 500") no longer starts at offset+1 (3). That must raise
    # rather than silently absorbing unrelated postings into the job list.
    fake = FakeSession({
        scrapers.GRIFOLS_SEARCH + "0": FakeResponse(GRIFOLS_PAGE1),
        scrapers.GRIFOLS_SEARCH + "2": FakeResponse(GRIFOLS_PAGE2_FILTER_DROPPED),
    })
    with pytest.raises(ValueError):
        scrapers.grifols(fake)


def test_leo_pharma_returns_empty_when_no_ireland_postings():
    # Real observed shape: LEO Pharma currently has zero open Ireland roles,
    # and the SuccessFactors site omits the results table entirely (no
    # paginationLabel, no data-row) rather than rendering a "0 results" page.
    fake = FakeSession({scrapers.LEO_SEARCH + "0": FakeResponse(b"<div>no results</div>")})
    jobs = scrapers.leo_pharma(fake)
    assert jobs == []


LEO_SINGLE_PAGE = b"""<span class="paginationLabel">Results <b>1 \xe2\x80\x93 1</b> of <b>1</b></span>
<table>
<tbody>
<tr class="data-row">
    <td class="colTitle"><span class="jobTitle hidden-phone">
        <a href="/job/Dublin-Clinical-Research-Associate/1387026233/" class="jobTitle-link">Clinical Research Associate</a>
    </span></td>
</tr>
</tbody>
</table>"""


def test_leo_pharma_parses_rows_when_present():
    # Same SuccessFactors job2web markup as Grifols, verified live to be the
    # identical platform -- exercised here in case Leo Pharma later posts an
    # Irish role.
    fake = FakeSession({scrapers.LEO_SEARCH + "0": FakeResponse(LEO_SINGLE_PAGE)})
    jobs = scrapers.leo_pharma(fake)
    assert jobs[0].title == "Clinical Research Associate"
    assert jobs[0].company == "Leo Pharma"
    assert jobs[0].url == "https://jobs.leo-pharma.com/job/Dublin-Clinical-Research-Associate/1387026233/"


def test_leo_pharma_in_registry():
    assert "Leo Pharma" in scrapers.SCRAPERS


# Trimmed from careers.iconplc.com's Radancy TalentBrew location page (live,
# 2026-11-21): 35 Ireland roles, 15 to a page; a page past the end is empty.
def _icon_tile(job_id, slug, title, location):
    return (f'<li class="search-results-list__item"><div class="search-results-list__content">'
            f'<h2 class="search-results-list__job-title"><a class="search-results-list__job-link" '
            f'href="/job/dublin/{slug}/3784/{job_id}" data-job-id="{job_id}" id="job-{job_id}">{title}</a>'
            f'</h2><ul class="search-results-list__job-info-list"><li class="search-results-list__job-info '
            f'job-location"> {location} </li></ul></div><div class="search-results-list__saved-job-container">'
            f'<button type="button" class="js-save-job-btn" data-job-id="{job_id}" data-org-id="3784">'
            f'Save</button></div></li>')


def _icon_page(*tiles):
    return ('<p id="search-results-headline-label">35 jobs found in Ireland</p>'
            '<ul id="search-results-jobs" class="search-results-list__list" data-results-count="35">'
            + "".join(tiles) + "</ul>").encode()


ICON_PAGE1 = _icon_page(
    _icon_tile("46757300096", "revenue-accountant", "Revenue Accountant", "Dublin, Leinster"),
    _icon_tile("46562888704", "ai-engineer", "AI Engineer", "Dublin, Leinster + Additional Locations"),
)
ICON_PAGE2 = _icon_page(
    _icon_tile("46562851776", "manager-payroll", "Manager, Payroll", "Dublin, Leinster"),
)
ICON_PAGE3 = _icon_page()


def test_icon_reads_talentbrew_ireland_location_pages_until_empty():
    # ICON moved to Radancy TalentBrew on 2026-11-16: /jobs?q=Ireland now
    # redirects to a keyword search over all 870 roles worldwide. The
    # Ireland location facet (GeoNames 2963597) excludes Northern Ireland.
    fake = FakeSession({
        scrapers.ICON_URL + "/3": FakeResponse(ICON_PAGE3),
        scrapers.ICON_URL + "/2": FakeResponse(ICON_PAGE2),
        scrapers.ICON_URL + "/1": FakeResponse(ICON_PAGE1),
    })
    jobs = scrapers.icon(fake)
    assert [j.title for j in jobs] == ["Revenue Accountant", "AI Engineer", "Manager, Payroll"]
    assert jobs[0].url == "https://careers.iconplc.com/job/dublin/revenue-accountant/3784/46757300096"
    assert jobs[0].portal_url == scrapers.ICON_URL
    assert scrapers.ICON_URL == "https://careers.iconplc.com/location/ireland-jobs/3784/2963597/2"


def test_talentbrew_stops_when_a_page_only_repeats_earlier_roles():
    # A guard against a site that wraps back to page 1 past the end, as
    # Viatris' Workday tenant does: no new role on a page ends the scrape.
    fake = FakeSession({
        scrapers.ICON_URL + "/2": FakeResponse(ICON_PAGE1),
        scrapers.ICON_URL + "/1": FakeResponse(ICON_PAGE1),
    })
    jobs = scrapers.icon(fake)
    assert [j.title for j in jobs] == ["Revenue Accountant", "AI Engineer"]
    assert len(fake.calls) == 2


def test_icon_in_registry():
    assert "ICON" in scrapers.SCRAPERS


def test_batch_c_registry_contains_all_companies():
    assert {"Alkermes", "Teva", "Viatris", "Grifols", "Leo Pharma", "ICON"} <= set(scrapers.SCRAPERS)


def test_johnson_and_johnson_is_retired():
    # careers.jnj.com sits behind a Cloudflare JS challenge since 2026-08-06
    # (confirmed live: "Just a moment..." page, HTTP 403). Not scrapeable
    # over plain HTTP, so it must not be in the registry any more.
    assert "Johnson & Johnson" not in scrapers.SCRAPERS
    assert not hasattr(scrapers, "johnson_and_johnson")


ASTELLAS_SF_PAGE = b"""<span class="paginationLabel">Results <b>1 \xe2\x80\x93 2</b> of <b>2</b></span>
<table><tr class="data-row"><td><a class="jobTitle-link" href="/job/QC-Systems-Engineer/1428911300/">QC Systems Engineer</a></td></tr>
<tr class="data-row"><td><a class="jobTitle-link" href="/job/Co_-Kerry-Management-Accountant/1429037700/">Management Accountant</a></td></tr></table>"""


def test_astellas_parses_successfactors_site():
    # astellas.avature.net went 404 on 2026-08-21; careers.astellas.com is
    # now a SuccessFactors job2web site (same platform as AIB/EY/Leo Pharma).
    fake = FakeSession({
        "https://careers.astellas.com/search/?q=&locationsearch=Ireland&startrow=0": FakeResponse(ASTELLAS_SF_PAGE),
    })
    jobs = scrapers.astellas(fake)
    assert [j.title for j in jobs] == ["QC Systems Engineer", "Management Accountant"]
    assert jobs[0].url == "https://careers.astellas.com/job/QC-Systems-Engineer/1428911300/"
    assert jobs[0].company == "Astellas"
    assert jobs[0].portal_url == scrapers.ASTELLAS_PORTAL


def test_astellas_returns_empty_when_no_ireland_postings():
    fake = FakeSession({
        "https://careers.astellas.com/search/?q=&locationsearch=Ireland&startrow=0": FakeResponse(b"<div>no rows</div>"),
    })
    assert scrapers.astellas(fake) == []
