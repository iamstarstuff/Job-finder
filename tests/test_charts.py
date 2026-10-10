import pandas as pd
from datetime import datetime, timedelta

from dashboard import charts
from jobfinder import storage
from jobfinder.models import Job
from tests.conftest import save_reading


def test_palette_has_every_role_from_the_spec():
    assert set(charts.PALETTE) == {
        "bar", "pharma", "tech", "ordinal", "neutral", "categorical", "sequential",
        "grid", "ink", "muted", "border",
    }
    assert charts.PALETTE["categorical"] == ["#1F7F5C", "#7A5BC0", "#C46A1E", "#2A6FC9", "#B8407A"]
    assert charts.PALETTE["ordinal"] == ["#81B19B", "#6E9D88", "#5A8974", "#487662", "#356350", "#23513E", "#0F3F2E"]
    assert len(charts.PALETTE["sequential"]) == 6
    assert charts.SENIORITY_ORDER == ["Intern/Graduate", "Junior", "Mid", "Senior", "Lead/Principal",
                                      "Manager", "Director+", "Not stated"]


def test_figure_applies_chart_chrome_and_no_title():
    fig = charts._figure()
    fig.barh(pd.DataFrame({"k": ["a"], "n": [1]}), x="k", y="n", color=charts.PALETTE["bar"])
    option = fig.to_option()
    assert "title" not in option
    assert option["tooltip"]["backgroundColor"] == "#FFFFFF"
    assert option["tooltip"]["axisPointer"] == {"type": "shadow"}
    assert option["yAxis"]["splitLine"]["lineStyle"] == {"color": charts.PALETTE["grid"], "type": "solid"}
    assert option["grid"]["containLabel"] is True


def test_figure_can_switch_to_item_tooltips_for_heatmaps():
    fig = charts._figure(trigger="item")
    fig.barh(pd.DataFrame({"k": ["a"], "n": [1]}), x="k", y="n", color=charts.PALETTE["bar"])
    assert fig.to_option()["tooltip"]["trigger"] == "item"


def test_chart_payload_serialises_to_the_api_contract():
    payload = charts.ChartPayload(option={"series": []}, columns=["A"], rows=[[1]],
                                  drilldown={"dimension": "skill", "key": "name"})
    assert payload.to_dict() == {"option": {"series": []}, "columns": ["A"], "rows": [[1]],
                                 "drilldown": {"dimension": "skill", "key": "name"}, "height": "360px",
                                 "note": None}
    empty = charts._empty(["A"], {"dimension": "skill", "key": "name"})
    assert empty.rows == [] and empty.option == {} and empty.drilldown["dimension"] == "skill"


NOW = datetime(2026, 9, 15, 12, 0, 0)

_seeded_counter = 0

def _seeded(tmp_path):
    """MSD (pharma): Senior QC Analyst (GMP+SAP, Senior) and Director of Quality
    (GMP, Director+) on 09-09, both Quality. Google (tech): Data Scientist
    (Python, seniority not stated, Data Science) on 09-14."""
    global _seeded_counter
    _seeded_counter += 1
    conn = storage.connect(tmp_path / f"c{_seeded_counter}.db")
    qc = Job("MSD", "Senior QC Analyst", "https://m/1", "p")
    director = Job("MSD", "Director of Quality", "https://m/2", "p")
    ds = Job("Google", "Data Scientist", "https://g/1", "p", sector="tech")
    storage.record_company_snapshot(conn, "MSD", [qc, director], "2026-09-09T10:00:00")
    storage.record_company_snapshot(conn, "Google", [ds], "2026-09-14T10:00:00")
    save_reading(conn, qc, role_family="Quality", seniority="Senior", skills=["GMP", "SAP"])
    save_reading(conn, director, role_family="Quality", seniority="Director+", skills=["GMP"])
    save_reading(conn, ds, role_family="Data Science", skills=["Python"])
    return conn


def test_skills_in_demand_builds_sorted_single_hue_bars(tmp_path):
    payload = charts.skills_in_demand(_seeded(tmp_path), None, 0, now=NOW)
    option = payload.option
    assert option["yAxis"]["data"] == ["SAP", "Python", "GMP"]  # reversed so GMP renders on top
    series = option["series"][0]
    assert series["name"] == "Roles" and series["data"] == [1, 1, 2]
    assert series["itemStyle"] == {"borderRadius": [0, 4, 4, 0], "color": charts.PALETTE["bar"]}
    assert series["barMaxWidth"] == 20
    assert option["legend"]["show"] is False
    assert payload.columns == ["Skill", "Roles"]
    assert payload.rows == [["GMP", 2], ["Python", 1], ["SAP", 1]]
    assert payload.drilldown == {"dimension": "skill", "key": "name"}
    assert payload.height == "420px"


def test_skills_in_demand_scopes_by_sector_and_is_empty_outside_window(tmp_path):
    conn = _seeded(tmp_path)
    assert charts.skills_in_demand(conn, "tech", 0, now=NOW).rows == [["Python", 1]]
    late = datetime(2027, 1, 1, 12, 0, 0)
    empty = charts.skills_in_demand(conn, None, 4, now=late)
    assert empty.rows == [] and empty.option == {} and empty.drilldown["dimension"] == "skill"


def test_hiring_velocity_home_has_two_named_series_and_legend(tmp_path):
    payload = charts.hiring_velocity(_seeded(tmp_path), None, 4, now=NOW)
    option = payload.option
    assert option["xAxis"]["data"] == ["17 Aug", "24 Aug", "31 Aug", "7 Sep", "14 Sep"]
    assert [s["name"] for s in option["series"]] == ["Pharma", "Tech"]
    assert [s["itemStyle"]["color"] for s in option["series"]] == [charts.PALETTE["pharma"], charts.PALETTE["tech"]]
    assert option["series"][0]["data"] == [0, 0, 0, 2, 0]
    assert option["series"][1]["data"] == [0, 0, 0, 0, 1]
    assert option["series"][0]["lineStyle"]["width"] == 2 and option["series"][0]["symbolSize"] == 8
    assert option["legend"]["show"] is True
    assert option["tooltip"]["axisPointer"] == {"type": "line"}
    assert payload.columns == ["Week", "Pharma", "Tech"]
    assert payload.rows[3] == ["2026-09-07", 2, 0]
    assert payload.drilldown is None


def test_hiring_velocity_sector_page_is_a_single_area_series_without_legend(tmp_path):
    option = charts.hiring_velocity(_seeded(tmp_path), "pharma", 4, now=NOW).option
    assert [s["name"] for s in option["series"]] == ["New jobs"]
    assert option["series"][0]["areaStyle"] == {"opacity": 0.1}
    assert option["series"][0]["itemStyle"]["color"] == charts.PALETTE["bar"]
    assert option["legend"]["show"] is False


def test_who_is_hiring_ranks_by_open_roles_and_tables_every_company(tmp_path):
    payload = charts.who_is_hiring(_seeded(tmp_path), None, 4, now=NOW)
    assert payload.option["yAxis"]["data"] == ["Google", "MSD"]  # reversed: MSD (2 open) on top
    assert payload.option["series"][0]["name"] == "Open roles"
    assert payload.columns == ["Company", "Open roles", "New in window", "New in previous window"]
    assert payload.rows == [["MSD", 2, 2, 0], ["Google", 1, 1, 0]]
    assert payload.drilldown == {"dimension": "company", "key": "name"}
    all_time = charts.who_is_hiring(_seeded(tmp_path), None, 0, now=NOW)
    assert all_time.rows[0] == ["MSD", 2, 2, ""]  # no previous window when weeks == 0


def test_skill_trend_is_a_share_heatmap_with_complete_axes(tmp_path):
    payload = charts.skill_trend(_seeded(tmp_path), None, 4, now=NOW)
    option = payload.option
    assert option["xAxis"]["data"] == ["17 Aug", "24 Aug", "31 Aug", "7 Sep", "14 Sep"]
    assert option["yAxis"]["data"] == ["SAP", "Python", "GMP"]  # top skill on top
    assert option["tooltip"]["trigger"] == "item"
    assert option["visualMap"]["min"] == 0 and option["visualMap"]["max"] == 100.0
    assert option["visualMap"]["inRange"]["color"] == charts.PALETTE["sequential"]
    assert option["xAxis"]["axisLabel"]["interval"] == 0     # show every weekly label, not just the ends
    assert option["xAxis"]["axisLabel"]["rotate"] == 45
    cells = {(x, y): v for x, y, v in option["series"][0]["data"]}
    assert cells[(3, 2)] == 100.0   # GMP, week of 7 Sep: 2 of 2 enriched jobs
    assert cells[(4, 2)] == 0.0     # GMP, week of 14 Sep: 0 of 1 (zero cells stay on the axis)
    assert cells[(4, 1)] == 100.0   # Python, week of 14 Sep
    assert payload.columns == ["Week", "Skill", "Roles needing it", "Roles read that week", "Share %"]
    assert ["2026-09-07", "GMP", 2, 2, 100.0] in payload.rows
    assert payload.drilldown == {"dimension": "skill", "key": "row"}


def test_skill_trend_thins_x_axis_labels_beyond_fourteen_columns(tmp_path):
    conn = _seeded(tmp_path)
    # One extra enriched job, dated 27 weeks before NOW, so the 26-week
    # window (cutoff-driven, not data-driven) spans 27 weekly columns.
    old_date = (NOW - timedelta(weeks=27)).isoformat(timespec="seconds")
    storage.record_company_snapshot(conn, "Pfizer", [
        Job("Pfizer", "Old Role", "https://p/1", "p"),
    ], old_date)
    save_reading(conn, Job("Pfizer", "Old Role", "https://p/1", "p"), skills=["Old"])

    payload = charts.skill_trend(conn, None, 26, now=NOW)
    option = payload.option
    assert len(option["xAxis"]["data"]) == 27
    assert option["xAxis"]["axisLabel"]["interval"] == 1


def test_part_one_builders_are_registered():
    assert {"skills-in-demand", "hiring-velocity", "who-is-hiring", "skill-trend"} <= set(charts.CHARTS)


def test_seniority_mix_is_a_100_percent_stack_in_fixed_tier_order(tmp_path):
    payload = charts.seniority_mix(_seeded(tmp_path), None, 4, now=NOW)
    option = payload.option
    assert option["yAxis"]["data"] == ["Google", "MSD"]  # MSD has 2 roles read: on top
    assert [s["name"] for s in option["series"]] == charts.SENIORITY_ORDER
    assert [s["itemStyle"]["color"] for s in option["series"]] == charts.PALETTE["ordinal"] + [charts.PALETTE["neutral"]]
    assert all(s["stack"] == "total" for s in option["series"])
    by_name = {s["name"]: s["data"] for s in option["series"]}
    assert by_name["Senior"] == [0.0, 50.0] and by_name["Director+"] == [0.0, 50.0]
    assert by_name["Not stated"] == [100.0, 0.0]
    assert option["xAxis"]["max"] == 100 and option["xAxis"]["axisLabel"]["formatter"] == "{value}%"
    assert payload.columns == ["Company"] + charts.SENIORITY_ORDER + ["Roles read"]
    assert payload.rows == [["MSD", 0, 0, 0, 1, 0, 0, 1, 0, 2], ["Google", 0, 0, 0, 0, 0, 0, 0, 1, 1]]
    assert payload.drilldown == {"dimension": "seniority", "key": "seriesName"}
    assert payload.height == "128px"


def test_company_families_is_a_share_heatmap_of_claude_role_families(tmp_path):
    conn = _seeded(tmp_path)
    payload = charts.company_families(conn, "pharma", 0, now=NOW)
    option = payload.option
    assert option["xAxis"]["data"] == ["Quality"] and option["yAxis"]["data"] == ["MSD"]
    assert option["xAxis"]["axisLabel"]["rotate"] == 30 and option["xAxis"]["axisLabel"]["interval"] == 0
    assert option["visualMap"]["min"] == 0 and option["visualMap"]["max"] == 100
    assert {(x, y): v for x, y, v in option["series"][0]["data"]} == {(0, 0): 100.0}
    assert payload.columns == ["Company", "Role family", "Roles", "Share %"]
    assert payload.rows == [["MSD", "Quality", 2, 100.0]]
    assert payload.drilldown == {"dimension": "company_family", "key": "cell"}
    both = charts.company_families(conn, None, 0, now=NOW).option
    assert both["xAxis"]["data"] == ["Quality", "Data Science"]  # largest family first
    assert both["yAxis"]["data"] == ["Google", "MSD"]            # MSD (2) renders on top


def test_days_to_close_uses_min_closed_three_and_sorts_longest_first(tmp_path):
    conn = _seeded(tmp_path)
    assert charts.days_to_close(conn, None, 0, now=NOW).rows == []  # nothing closed yet
    roles = [Job("BMS", f"Role {i}", f"https://b/{i}", "p") for i in range(3)]
    # all three open on 08-01; one drops out every ten days -> open for 10, 20 and 30 days
    storage.record_company_snapshot(conn, "BMS", roles, "2026-08-01T10:00:00")
    storage.record_company_snapshot(conn, "BMS", roles, "2026-08-11T10:00:00")
    storage.record_company_snapshot(conn, "BMS", roles[1:], "2026-08-21T10:00:00")   # Role 0 closes, last seen 08-11
    storage.record_company_snapshot(conn, "BMS", roles[2:], "2026-08-31T10:00:00")   # Role 1 closes, last seen 08-21
    storage.record_company_snapshot(conn, "BMS", [], "2026-09-01T10:00:00")          # Role 2 closes, last seen 08-31
    payload = charts.days_to_close(conn, None, 0, now=NOW)
    assert payload.rows == [["BMS", 20.0, 3]]
    assert payload.option["yAxis"]["data"] == ["BMS"]
    assert payload.option["series"][0]["name"] == "Median days open"
    assert payload.columns == ["Company", "Median days open", "Closed jobs"]
    assert payload.drilldown == {"dimension": "company", "key": "name"}


def test_registry_matches_the_spec_inventory():
    assert set(charts.CHARTS) == {
        "skills-in-demand", "hiring-velocity", "who-is-hiring", "skill-trend",
        "seniority-mix", "company-families", "days-to-close",
        "what-to-learn", "experience-by-family", "openings-by-family",
    }
    for builder in charts.CHARTS.values():
        assert callable(builder)


from pathlib import Path


def test_palette_matches_base_html():
    html = (Path(__file__).resolve().parent.parent / "dashboard" / "templates" / "base.html").read_text()
    for value in charts.PALETTE.values():
        for hex_value in (value if isinstance(value, list) else [value]):
            assert hex_value in html, f"{hex_value} missing from base.html tokens"


def _learn_seeded(tmp_path):
    """Six Google tech roles first seen 09-10: five ML/AI (three Senior, two
    Mid), one Cloud/Platform; Python in all, PyTorch in two; years 3,5,7,-,4 / 6."""
    conn = storage.connect(tmp_path / "learn.db")
    jobs = [Job("Google", f"Role {i}", f"https://g/{i}", "p", sector="tech") for i in range(6)]
    storage.record_company_snapshot(conn, "Google", jobs, "2026-09-10T10:00:00")
    for i, job in enumerate(jobs):
        save_reading(conn, job, role_family="ML/AI" if i < 5 else "Cloud/Platform",
                     seniority="Senior" if i < 3 else "Mid",
                     skills=["Python", "PyTorch"] if i < 2 else ["Python"],
                     min_years_experience=[3, 5, 7, None, 4, 6][i])
    return conn


def test_what_to_learn_shows_x_of_n_and_refuses_tiny_samples(tmp_path):
    conn = _learn_seeded(tmp_path)
    payload = charts.what_to_learn(conn, "tech", 0, now=NOW)
    assert payload.option["yAxis"]["data"] == ["PyTorch", "Python"]
    assert payload.option["xAxis"]["max"] == 6
    assert payload.option["series"][0]["label"]["formatter"] == "{c} of 6"
    assert payload.columns == ["Skill", "Roles", "Of"]
    assert payload.rows == [["Python", 6, 6], ["PyTorch", 2, 6]]
    assert payload.note == "Based on 6 roles."
    assert payload.drilldown == {"dimension": "skill", "key": "name"}
    assert charts.what_to_learn(conn, "tech", 0, now=NOW, families=("ML/AI",)).rows[0] == ["Python", 5, 5]
    tiny = charts.what_to_learn(conn, "tech", 0, now=NOW, families=("ML/AI",), levels=("Senior",))
    assert tiny.option == {} and tiny.rows == []
    assert tiny.note == "Too few roles (3) for these choices."


def test_experience_asked_labels_stated_counts_and_lists_thin_families(tmp_path):
    payload = charts.experience_asked(_learn_seeded(tmp_path), "tech", 0, now=NOW)
    option = payload.option
    assert option["yAxis"]["data"] == ["ML/AI"]
    datum = option["series"][0]["data"][0]
    assert datum["value"] == 4.5 and datum["label"]["formatter"] == "stated in 4 of 5"
    assert payload.columns == ["Role family", "Median years", "Stated", "Roles"]
    assert payload.rows == [["ML/AI", 4.5, 4, 5], ["Cloud/Platform", "", 1, 1]]
    assert payload.note == "Too few stated: Cloud/Platform."
    assert payload.drilldown == {"dimension": "role_family", "key": "name"}


def test_openings_by_family_is_one_coloured_line_per_family(tmp_path):
    payload = charts.openings_by_family(_learn_seeded(tmp_path), "tech", 4, now=NOW)
    option = payload.option
    assert option["xAxis"]["data"] == ["17 Aug", "24 Aug", "31 Aug", "7 Sep", "14 Sep"]
    assert [s["name"] for s in option["series"]] == ["ML/AI", "Cloud/Platform"]
    assert [s["itemStyle"]["color"] for s in option["series"]] == charts.PALETTE["categorical"][:2]
    assert option["series"][0]["data"] == [0, 0, 0, 5, 0]
    assert payload.columns == ["Week", "ML/AI", "Cloud/Platform"]
    assert payload.rows[3] == ["2026-09-07", 5, 1]
    assert payload.drilldown == {"dimension": "role_family", "key": "seriesName"}
    assert charts.openings_by_family(_learn_seeded(tmp_path), "pharma", 4, now=NOW).option == {}
