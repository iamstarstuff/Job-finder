from werkzeug.datastructures import MultiDict

from dashboard import job_search
from dashboard.job_search import Filters
from jobfinder.analytics import JobRecord


def rec(i, **kw):
    fields = dict(id=i, company="Google", title=f"Role {i}", url=f"https://g/{i}", sector="tech",
                  first_seen=f"2026-10-{10 - i % 9:02d}T08:00:00", is_active=True, description="desc",
                  read_by_claude=True, role_family="ML/AI", seniority="Senior", min_years=5,
                  work_mode="hybrid", contract_type="permanent", salary_min=None, salary_max=None,
                  salary_currency=None, salary_period=None, reason="Fits.", skills=("Python",), languages=())
    fields.update(kw)
    return JobRecord(**fields)


RECORDS = [
    rec(1, role_family="ML/AI", seniority="Senior", min_years=5, skills=("Python", "PyTorch")),
    rec(2, role_family="Data Science", seniority="Mid", min_years=None, work_mode="not_stated"),
    rec(3, role_family="Cloud/Platform", seniority=None, min_years=8, company="AWS", skills=("Kubernetes",)),
    rec(4, sector="pharma", company="MSD", role_family="Quality", seniority="Junior", min_years=2,
        work_mode="onsite", contract_type="internship", reason=None, skills=("GMP",)),
    rec(5, read_by_claude=False, role_family=None, seniority=None, min_years=None, work_mode=None,
        contract_type=None, company="APC", sector="pharma", title="Warehouse Lead", skills=(), description=None),
    rec(6, is_active=False, title="Closed Role"),
]


def run(**args):
    return job_search.search(RECORDS, Filters.from_args(MultiDict(args)))


def titles(result):
    return [r.title for r in result.cards]


def test_defaults_show_active_jobs_newest_first_including_unread():
    result = run()
    assert "Closed Role" not in titles(result) and "Warehouse Lead" in titles(result)
    assert result.total == 5 and result.page == 1 and result.pages == 1
    assert "Closed Role" in titles(run(all="1"))


def test_unknown_values_are_ignored():
    f = Filters.from_args(MultiDict([("sector", "bogus"), ("seniority", "Wizard"), ("years", "3"),
                                     ("mode", "space"), ("page", "x"), ("family", "Nonsense")]))
    assert (f.sector, f.seniority, f.years, f.mode, f.page) == ("", (), None, (), 1)
    assert job_search.search(RECORDS, f).total == 5  # the unknown family is dropped too


def test_family_filter_hides_unread_jobs_and_counts_are_disjunctive():
    result = job_search.search(RECORDS, Filters.from_args(MultiDict([("family", "ML/AI")])))
    assert titles(result) == ["Role 1"]
    family = {c.value: (c.count, c.selected) for c in result.facets["family"]}
    assert family["ML/AI"] == (1, True) and family["Data Science"] == (1, False)  # own group not applied
    seniority = {c.value: c.count for c in result.facets["seniority"]}
    assert seniority == {"Senior": 1}                                              # other groups applied


def test_years_bucket_keeps_jobs_that_state_no_years():
    result = run(years="5")
    assert set(titles(result)) == {"Role 1", "Role 2", "Role 4"}
    years = {c.value: c.count for c in result.facets["years"]}
    assert years == {"": 5, "2": 2, "5": 3, "8": 4}


def test_seniority_not_stated_and_multiple_values():
    result = job_search.search(RECORDS, Filters.from_args(MultiDict([("seniority", "Not stated"), ("seniority", "Mid")])))
    assert set(titles(result)) == {"Role 2", "Role 3"}


def test_mode_contract_sector_and_company():
    assert titles(run(mode="onsite")) == ["Role 4"]
    assert titles(run(contract="internship")) == ["Role 4"]
    assert set(titles(run(sector="pharma"))) == {"Role 4", "Warehouse Lead"}
    assert titles(run(company="AWS")) == ["Role 3"]
    companies = {c.value: c.count for c in run(company="AWS").companies}
    assert companies == {"APC": 1, "AWS": 1, "Google": 2, "MSD": 1}


def test_search_matches_titles_and_skills_and_old_skill_param():
    assert titles(run(q="kubernetes")) == ["Role 3"]
    assert titles(run(q="warehouse")) == ["Warehouse Lead"]
    assert titles(run(skill="pytorch")) == ["Role 1"]


def test_paging_and_out_of_range_pages():
    many = [rec(i, first_seen=f"2026-10-01T{i // 60:02d}:{i % 60:02d}:00") for i in range(120)]
    result = job_search.search(many, Filters.from_args(MultiDict({"page": "3"})))
    assert (result.page, result.pages, len(result.cards), result.total) == (3, 3, 20, 120)
    assert job_search.search(many, Filters.from_args(MultiDict({"page": "99"}))).page == 3


def test_query_keeps_every_filter_and_counts_active_choices():
    f = Filters.from_args(MultiDict([("sector", "tech"), ("family", "ML/AI"), ("family", "Data Science"),
                                     ("years", "5"), ("all", "1")]))
    assert f.active_count == 4
    assert f.query(page=2) == "sector=tech&family=ML%2FAI&family=Data+Science&years=5&all=1&page=2"


def test_card_facts_show_only_stated_fields():
    assert job_search.card_facts(rec(1, salary_min=90000.0, salary_max=92000.0, salary_currency="EUR",
                                     salary_period="year")) == ["Senior", "5+ yrs", "Hybrid", "Permanent",
                                                                "€90–92k a year"]
    assert job_search.card_facts(rec(2, seniority="Not stated", min_years=None, work_mode="not_stated",
                                     contract_type="not_stated")) == []


def test_salary_text_formats():
    assert job_search.salary_text(rec(1, salary_min=190800.0, salary_max=300300.0, salary_currency="USD",
                                      salary_period="year")) == "USD 191–300k a year"
    assert job_search.salary_text(rec(1, salary_min=50000.0, salary_max=50000.0, salary_currency="EUR",
                                      salary_period="year")) == "€50k a year"
    assert job_search.salary_text(rec(1, salary_min=25.0, salary_max=30.0, salary_currency="EUR",
                                      salary_period="hour")) == "€25–30 an hour"
    assert job_search.salary_text(rec(1)) is None
