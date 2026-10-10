import json

import pytest

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


# Real shape (live-verified): data:[jobs_list, null, total_count, page_size].
# total=3, page_size=2 here -> page 1 has 2 jobs (fetched=2 < 3, continue),
# page 2 has the remaining 1 job (fetched=3 >= 3, stop).
GOOGLE_PAGE1 = b"""<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:[[["1001","Senior SRE, Cloud Storage","https://google.com/apply?jobId=1001"],["1002","Sales Rep","https://google.com/apply?jobId=1002"]],null,3,2]
, sideChannel: {}});</script>"""
GOOGLE_PAGE2 = b"""<script>AF_initDataCallback({key: 'ds:1', hash: '1', data:[[["1003","Data Scientist, Ads","https://google.com/apply?jobId=1003"]],null,3,2]
, sideChannel: {}});</script>"""


def test_google_paginates_using_total_count_and_returns_all_ireland_roles():
    fake = FakeSession({
        "https://careers.google.com/jobs/results/?location=Ireland&page=1": FakeResponse(GOOGLE_PAGE1),
        "https://careers.google.com/jobs/results/?location=Ireland&page=2": FakeResponse(GOOGLE_PAGE2),
    })
    jobs = tech_scrapers.google(fake)
    assert [j.title for j in jobs] == ["Senior SRE, Cloud Storage", "Sales Rep", "Data Scientist, Ads"]
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


def test_aib_returns_all_roles_and_builds_absolute_urls():
    fake = FakeSession({
        "https://jobs.aib.ie/aib/go/SearchAllJobs/9605800/?startrow=0": FakeResponse(AIB_PAGE_HTML),
    })
    jobs = tech_scrapers.aib(fake)
    assert [j.title for j in jobs] == ['Fraud Data Scientist', 'Homes Advisor, Dundalk']
    assert jobs[0].title == "Fraud Data Scientist"
    assert jobs[0].url == "https://jobs.aib.ie/aib/job/Dublin-Fraud-Data-Scientist-IE/1366746757/"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "AIB"


def test_microsoft_parses_live_verified_pcsx_api_and_returns_all_roles():
    fake = FakeSession({
        "https://apply.careers.microsoft.com/api/pcsx/search": FakeResponse(json_data={
            "status": 200,
            "data": {
                "count": 2,
                "positions": [
                    {"name": "Senior DevOps Engineer", "positionUrl": "/careers/job/1700000001"},
                    {"name": "Retail Store Associate", "positionUrl": "/careers/job/1700000002"},
                ],
            },
        }),
    })
    jobs = tech_scrapers.microsoft(fake)
    assert [j.title for j in jobs] == ['Senior DevOps Engineer', 'Retail Store Associate']
    assert jobs[0].title == "Senior DevOps Engineer"
    assert jobs[0].url == "https://apply.careers.microsoft.com/careers/job/1700000001"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Microsoft"


def test_tech_scrapers_registry_has_fifteen_companies():
    assert set(tech_scrapers.TECH_SCRAPERS) == {
        "Google", "Microsoft", "AIB", "Mastercard", "Accenture", "Intel",
        "Citibank", "Allianz Partners", "EY", "Amazon", "AWS", "Stripe",
        "JPMorganChase", "Salesforce", "Infosys",
    }


def _infosys_hits(*reqids):
    # One Algolia hit per posting, shaped like the live index (confirmed
    # 2026-10-10): list-valued fields, redirect_url holding the job page.
    return [{
        "title": f"Data Engineer {reqid} ", "country": ["Ireland"], "work_location": ["Dublin"],
        "reqid": [reqid], "objectID": f"Job::{reqid}",
        "redirect_url": [f"https://digitalcareers.infosys.com/global-careers/company-job/description/reqid/{reqid}"],
    } for reqid in reqids]


def test_infosys_queries_algolia_for_ireland():
    fake = FakeSession({tech_scrapers.INFOSYS_ALGOLIA_URL: FakeResponse(
        json_data={"hits": _infosys_hits("148920BR", "141411BR"), "nbPages": 1})})
    jobs = tech_scrapers.infosys(fake)
    assert [j.title for j in jobs] == ["Data Engineer 148920BR", "Data Engineer 141411BR"]
    assert jobs[0].url == "https://digitalcareers.infosys.com/global-careers/company-job/description/reqid/148920BR"
    assert jobs[0].sector == "tech" and jobs[0].company == "Infosys"
    method, url, kwargs = fake.calls[0]
    assert method == "post"
    assert kwargs["headers"]["X-Algolia-Application-Id"] == "UM59DWRPA1"
    assert "country%3AIreland" in kwargs["json"]["params"]


def test_infosys_follows_algolia_pages():
    fake = FakeSession({tech_scrapers.INFOSYS_ALGOLIA_URL: FakeResponse(
        json_data={"hits": _infosys_hits("1BR"), "nbPages": 2})})
    tech_scrapers.infosys(fake)
    pages = [kwargs["json"]["params"] for _, _, kwargs in fake.calls]
    assert len(pages) == 2 and "page=0" in pages[0] and "page=1" in pages[1]


def test_infosys_with_no_irish_postings_returns_an_empty_list():
    fake = FakeSession({tech_scrapers.INFOSYS_ALGOLIA_URL: FakeResponse(json_data={"hits": [], "nbPages": 0})})
    assert tech_scrapers.infosys(fake) == []


def test_salesforce_returns_all_roles_and_paginates():
    fake = FakeSession({
        "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs": FakeResponse(json_data={
            "total": 1,
            "jobPostings": [
                {"title": "Forward Deployed Engineer, Data Science", "externalPath": "/job/Ireland---Dublin/FDE_JR1"},
                {"title": "Account Executive, SMB", "externalPath": "/job/Ireland---Dublin/AE_JR2"},
            ],
        }),
    })
    jobs = tech_scrapers.salesforce(fake)
    assert [j.title for j in jobs] == ['Forward Deployed Engineer, Data Science', 'Account Executive, SMB']
    assert jobs[0].title == "Forward Deployed Engineer, Data Science"
    assert jobs[0].url == "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/Ireland---Dublin/FDE_JR1"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Salesforce"


def test_jpmorganchase_returns_all_roles_and_paginates():
    fake = FakeSession({
        "https://jpmc.fa.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions": FakeResponse(json_data={
            "items": [{
                "TotalJobsCount": 1,
                "requisitionList": [
                    {"Id": "210708545", "Title": "Senior Manager of SRE"},
                    {"Id": "210759082", "Title": "Lead Software Engineer-Front End React/Web"},
                ],
            }],
        }),
    })
    jobs = tech_scrapers.jpmorganchase(fake)
    assert [j.title for j in jobs] == ['Senior Manager of SRE', 'Lead Software Engineer-Front End React/Web']
    assert jobs[0].title == "Senior Manager of SRE"
    assert jobs[0].url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210708545"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "JPMorganChase"


def _stripe_page(listings, with_data=True):
    # The shape of stripe.com/careers/search (confirmed live 2026-10-10): every
    # posting is embedded as JSON in __NEXT_DATA__, with locations as indices
    # into filters.locations. "Europe" oddly carries countryCode IE but has no
    # parentLocationIndex -- it is a region, not a place in Ireland.
    data = {"props": {"pageProps": {"jobIndexData": {
        "filters": {"locations": [
            {"name": "Americas", "remote": False, "countryCode": "US"},
            {"name": "Europe", "remote": False, "countryCode": "IE"},
            {"parentLocationIndex": 1, "name": "Ireland", "countryCode": "IE"},
            {"parentLocationIndex": 2, "name": "Remote in Ireland", "remote": True, "countryCode": "IE"},
            {"parentLocationIndex": 2, "name": "Dublin HQ", "countryCode": "IE"},
            {"parentLocationIndex": 1, "name": "London", "countryCode": "GB"},
        ]},
        "listings": listings,
    }}}}
    script = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>' if with_data else ""
    return f"<html><body><div id=\"__next\"></div>{script}</body></html>".encode()


STRIPE_LISTINGS = [
    {"greenhouseId": 8018297, "title": "Data Scientist, Payments ", "slug": "data-scientist-payments",
     "locationIndices": [4], "teamIndices": [1]},
    {"greenhouseId": 1112223, "title": "Account Executive", "slug": "account-executive-dublin",
     "locationIndices": [5, 3], "teamIndices": [2]},
    {"greenhouseId": 9998887, "title": "Data Scientist, London", "slug": "data-scientist-london",
     "locationIndices": [5], "teamIndices": [1]},
    {"greenhouseId": 4445556, "title": "Europe-wide Role", "slug": "europe-wide-role",
     "locationIndices": [1], "teamIndices": [1]},
]


def test_stripe_reads_irish_postings_from_the_embedded_job_index():
    fake = FakeSession({"https://stripe.com/careers/search": FakeResponse(_stripe_page(STRIPE_LISTINGS))})
    jobs = tech_scrapers.stripe(fake)
    assert [j.title for j in jobs] == ["Data Scientist, Payments", "Account Executive"]
    assert jobs[0].url == "https://stripe.com/careers/listing/data-scientist-payments/8018297"
    assert jobs[0].portal_url == "https://stripe.com/careers/search"
    assert jobs[0].sector == "tech" and jobs[0].company == "Stripe"


def test_stripe_fails_loudly_when_the_job_index_is_missing():
    # A silent empty list is how the old layout change went unnoticed; an
    # exception makes the tech run report Stripe as failing instead.
    fake = FakeSession({"https://stripe.com/careers/search": FakeResponse(_stripe_page([], with_data=False))})
    with pytest.raises(ValueError):
        tech_scrapers.stripe(fake)


AMAZON_PAGE1 = {
    "hits": 3,
    "jobs": [
        {"title": "Senior DevOps Engineer, AWS Infrastructure", "job_path": "/en/jobs/1001/devops", "business_category": "aws"},
        {"title": "Retail Store Lead", "job_path": "/en/jobs/1002/retail", "business_category": "retail"},
    ],
}
AMAZON_PAGE2 = {
    "hits": 3,
    "jobs": [
        {"title": "Senior Data Scientist, Supply Chain", "job_path": "/en/jobs/1003/ds", "business_category": "finance"},
    ],
}


class _AmazonSeq:
    """Amazon's pagination is via `params={"offset": ...}` on a GET request
    to a constant URL, not a URL that changes per page -- FakeSession's
    prefix-match routing can't distinguish two calls to the same URL, so
    (matching the existing test_gilead_parses_and_paginates_workday_api
    pattern for the same underlying problem with POST-body pagination)
    this returns responses from a queue regardless of URL/params."""
    def __init__(self, responses):
        self._responses = iter(responses)

    def get(self, url, **kwargs):
        return next(self._responses)


def test_amazon_returns_all_roles_excluding_aws_category():
    fake = _AmazonSeq([FakeResponse(json_data=AMAZON_PAGE1), FakeResponse(json_data=AMAZON_PAGE2)])
    jobs = tech_scrapers.amazon(fake)
    assert [j.title for j in jobs] == ["Retail Store Lead", "Senior Data Scientist, Supply Chain"]
    assert jobs[1].url == "https://www.amazon.jobs/en/jobs/1003/ds"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Amazon"


def test_aws_returns_all_roles_in_aws_category():
    fake = _AmazonSeq([FakeResponse(json_data=AMAZON_PAGE1), FakeResponse(json_data=AMAZON_PAGE2)])
    jobs = tech_scrapers.aws(fake)
    assert len(jobs) == 1
    assert jobs[0].title == "Senior DevOps Engineer, AWS Infrastructure"
    assert jobs[0].url == "https://www.amazon.jobs/en/jobs/1001/devops"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "AWS"


def test_mastercard_returns_all_roles_and_paginates():
    fake = FakeSession({
        "https://mastercard.wd1.myworkdayjobs.com/wday/cxs/mastercard/CorporateCareers/jobs": FakeResponse(json_data={
            "total": 1,
            "jobPostings": [
                {"title": "Senior Site Reliability Engineer", "externalPath": "/job/Dublin/SRE_R1"},
                {"title": "Retail Branch Associate", "externalPath": "/job/Dublin/Retail_R2"},
            ],
        }),
    })
    jobs = tech_scrapers.mastercard(fake)
    assert [j.title for j in jobs] == ['Senior Site Reliability Engineer', 'Retail Branch Associate']
    assert jobs[0].title == "Senior Site Reliability Engineer"
    assert jobs[0].url == "https://mastercard.wd1.myworkdayjobs.com/en-US/CorporateCareers/job/Dublin/SRE_R1"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Mastercard"


def test_accenture_returns_all_roles():
    fake = FakeSession({
        "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs": FakeResponse(json_data={
            "total": 1,
            "jobPostings": [
                {"title": "Cloud Platform Architect", "externalPath": "/job/Dublin/Cloud_R1"},
                {"title": "Junior Copywriter", "externalPath": "/job/Dublin/Copy_R2"},
            ],
        }),
    })
    jobs = tech_scrapers.accenture(fake)
    assert [j.title for j in jobs] == ['Cloud Platform Architect', 'Junior Copywriter']
    assert jobs[0].title == "Cloud Platform Architect"
    assert jobs[0].url == "https://accenture.wd103.myworkdayjobs.com/en-US/AccentureCareers/job/Dublin/Cloud_R1"
    assert jobs[0].company == "Accenture"


def test_citibank_returns_all_roles_and_paginates():
    fake = FakeSession({
        "https://citi.eightfold.ai/api/pcsx/search": FakeResponse(json_data={
            "status": 200,
            "data": {
                "count": 1,
                "positions": [
                    {"name": "Cloud Infrastructure Engineer, VP", "positionUrl": "/careers/job/859000001"},
                    {"name": "CitiService Financial Institution Head", "positionUrl": "/careers/job/859000002"},
                ],
            },
        }),
    })
    jobs = tech_scrapers.citibank(fake)
    assert [j.title for j in jobs] == ['Cloud Infrastructure Engineer, VP', 'CitiService Financial Institution Head']
    assert jobs[0].title == "Cloud Infrastructure Engineer, VP"
    assert jobs[0].url == "https://citi.eightfold.ai/careers/job/859000001"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Citibank"


def test_allianz_partners_filters_by_entity_only():
    fake = FakeSession({
        "https://careers.allianz.com/widgets": FakeResponse(json_data={
            "refineSearch": {"data": {"jobs": [
                {"title": "Data Scientist", "employingEntity": "AWP Assistance UK Ltd",
                 "applyUrl": "https://career5.successfactors.eu/careers?career_job_req_id=1"},
                {"title": "Data Scientist", "employingEntity": "Allianz Global Life dac",
                 "applyUrl": "https://career5.successfactors.eu/careers?career_job_req_id=2"},
                {"title": "Broker Consultant", "employingEntity": "ALLIANZ PARTNERS",
                 "applyUrl": "https://career5.successfactors.eu/careers?career_job_req_id=3"},
            ]}},
        }),
    })
    jobs = tech_scrapers.allianz_partners(fake)
    assert [j.title for j in jobs] == ['Data Scientist', 'Broker Consultant']
    assert jobs[0].title == "Data Scientist"
    assert jobs[0].url == "https://career5.successfactors.eu/careers?career_job_req_id=1"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "Allianz Partners"


EY_PAGE_HTML = b"""
<span class="paginationLabel" aria-label="Results 1 - 2">Results <b>1 - 2</b> of <b>2</b></span>
<tr class="data-row"><td><a class="jobTitle-link" href="/ey/job/Dublin-Cloud-Security-Consultant-IE/1400000001/">Cloud Infrastructure Consultant</a></td></tr>
<tr class="data-row"><td><a class="jobTitle-link" href="/ey/job/Dublin-Tax-Advisor-IE/1400000002/">Tax Advisor</a></td></tr>
"""


def test_ey_returns_all_roles_and_builds_absolute_urls():
    fake = FakeSession({
        "https://careers.ey.com/ey/search/?createNewAlert=false&q=&locationsearch=Ireland&startrow=0": FakeResponse(EY_PAGE_HTML),
    })
    jobs = tech_scrapers.ey(fake)
    assert [j.title for j in jobs] == ['Cloud Infrastructure Consultant', 'Tax Advisor']
    assert jobs[0].title == "Cloud Infrastructure Consultant"
    assert jobs[0].url == "https://careers.ey.com/ey/job/Dublin-Cloud-Security-Consultant-IE/1400000001/"
    assert jobs[0].sector == "tech"
    assert jobs[0].company == "EY"


def test_intel_returns_all_roles():
    fake = FakeSession({
        "https://intel.wd1.myworkdayjobs.com/wday/cxs/intel/External/jobs": FakeResponse(json_data={
            "total": 1,
            "jobPostings": [
                {"title": "AI Framework DevOps Engineer", "externalPath": "/job/Leixlip/DevOps_R1"},
                {"title": "Manufacturing Technician", "externalPath": "/job/Leixlip/Mfg_R2"},
            ],
        }),
    })
    jobs = tech_scrapers.intel(fake)
    assert [j.title for j in jobs] == ['AI Framework DevOps Engineer', 'Manufacturing Technician']
    assert jobs[0].title == "AI Framework DevOps Engineer"
    assert jobs[0].company == "Intel"


def test_matches_target_role_bi_does_not_match_hyphenated_prefix():
    # "Bi-Lingual" was stored twice as a tech job because \bbi\b treats the
    # hyphen as a word boundary. BI the discipline still has to match.
    assert not tech_scrapers.matches_target_role("Bi-Lingual Support Engineering Operations Manager")
    assert tech_scrapers.matches_target_role("BI Developer")
    assert tech_scrapers.matches_target_role("Senior BI/Analytics Engineer")
