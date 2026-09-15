import pandas as pd
from datetime import datetime, timedelta

from dashboard import charts
from jobfinder import storage
from jobfinder.models import Job


def test_palette_has_every_role_from_the_spec():
    assert set(charts.PALETTE) == {
        "bar", "pharma", "tech", "ordinal", "neutral", "sequential",
        "grid", "ink", "muted", "border",
    }
    assert charts.PALETTE["ordinal"] == ["#8FB5A2", "#659A84", "#417C66", "#2F5D50"]
    assert len(charts.PALETTE["sequential"]) == 6
    assert charts.SENIORITY_ORDER == ["Junior", "Senior", "Lead", "Director", "Unspecified"]


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
                                 "drilldown": {"dimension": "skill", "key": "name"}, "height": "360px"}
    empty = charts._empty(["A"], {"dimension": "skill", "key": "name"})
    assert empty.rows == [] and empty.option == {} and empty.drilldown["dimension"] == "skill"


NOW = datetime(2026, 9, 15, 12, 0, 0)

_seeded_counter = 0

def _seeded(tmp_path):
    """MSD (pharma): GMP+SAP Senior on 09-09, GMP Director on 09-09.
    Google (tech): Python, no seniority, on 09-14. Nothing older than 4 weeks."""
    global _seeded_counter
    _seeded_counter += 1
    conn = storage.connect(tmp_path / f"c{_seeded_counter}.db")
    storage.record_company_snapshot(conn, "MSD", [
        Job("MSD", "Senior QC Analyst", "https://m/1", "p"),
        Job("MSD", "Director of Quality", "https://m/2", "p"),
    ], "2026-09-09T10:00:00")
    storage.record_company_snapshot(conn, "Google", [
        Job("Google", "Data Scientist", "https://g/1", "p", sector="tech"),
    ], "2026-09-14T10:00:00")
    ids = {u: conn.execute("SELECT id FROM jobs WHERE url=?", (u,)).fetchone()["id"]
           for u in ("https://m/1", "https://m/2", "https://g/1")}
    storage.save_enrichment(conn, ids["https://m/1"], "GMP and SAP", "Senior",
                            [("GMP", "Regulatory"), ("SAP", "Software")], "2026-09-09T11:00:00")
    storage.save_enrichment(conn, ids["https://m/2"], "GMP", "Director",
                            [("GMP", "Regulatory")], "2026-09-09T11:00:00")
    storage.save_enrichment(conn, ids["https://g/1"], "Python", None,
                            [("Python", "Software")], "2026-09-14T11:00:00")
    return conn


def test_skills_in_demand_builds_sorted_single_hue_bars(tmp_path):
    payload = charts.skills_in_demand(_seeded(tmp_path), None, 0, now=NOW)
    option = payload.option
    assert option["yAxis"]["data"] == ["SAP", "Python", "GMP"]  # reversed so GMP renders on top
    series = option["series"][0]
    assert series["name"] == "Jobs" and series["data"] == [1, 1, 2]
    assert series["itemStyle"] == {"borderRadius": [0, 4, 4, 0], "color": charts.PALETTE["bar"]}
    assert series["barMaxWidth"] == 20
    assert option["legend"]["show"] is False
    assert payload.columns == ["Skill", "Category", "Jobs"]
    assert payload.rows == [["GMP", "Regulatory", 2], ["Python", "Software", 1], ["SAP", "Software", 1]]
    assert payload.drilldown == {"dimension": "skill", "key": "name"}
    assert payload.height == "420px"


def test_skills_in_demand_scopes_by_sector_and_is_empty_outside_window(tmp_path):
    conn = _seeded(tmp_path)
    assert charts.skills_in_demand(conn, "tech", 0, now=NOW).rows == [["Python", "Software", 1]]
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
    assert payload.columns == ["Week", "Skill", "Jobs mentioning", "Enriched jobs that week", "Share %"]
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
    old_id = conn.execute("SELECT id FROM jobs WHERE url=?", ("https://p/1",)).fetchone()["id"]
    storage.save_enrichment(conn, old_id, "Old desc", None, [("Old", "Misc")], old_date)

    payload = charts.skill_trend(conn, None, 26, now=NOW)
    option = payload.option
    assert len(option["xAxis"]["data"]) == 27
    assert option["xAxis"]["axisLabel"]["interval"] == 1


def test_part_one_builders_are_registered():
    assert {"skills-in-demand", "hiring-velocity", "who-is-hiring", "skill-trend"} <= set(charts.CHARTS)


def test_seniority_mix_is_a_100_percent_stack_in_fixed_tier_order(tmp_path):
    payload = charts.seniority_mix(_seeded(tmp_path), None, 4, now=NOW)
    option = payload.option
    assert option["yAxis"]["data"] == ["Google", "MSD"]  # MSD has 2 enriched jobs: on top
    assert [s["name"] for s in option["series"]] == charts.SENIORITY_ORDER
    assert [s["itemStyle"]["color"] for s in option["series"]] == charts.PALETTE["ordinal"] + [charts.PALETTE["neutral"]]
    assert all(s["stack"] == "total" for s in option["series"])
    assert all(s["itemStyle"]["borderColor"] == "#FFFFFF" and s["itemStyle"]["borderWidth"] == 2 for s in option["series"])
    by_name = {s["name"]: s["data"] for s in option["series"]}
    assert by_name["Senior"] == [0.0, 50.0] and by_name["Director"] == [0.0, 50.0]
    assert by_name["Unspecified"] == [100.0, 0.0]
    assert option["xAxis"]["max"] == 100 and option["xAxis"]["axisLabel"]["formatter"] == "{value}%"
    assert option["legend"]["show"] is True
    assert payload.columns == ["Company"] + charts.SENIORITY_ORDER + ["Enriched jobs"]
    assert payload.rows == [["MSD", 0, 1, 0, 1, 0, 2], ["Google", 0, 0, 0, 0, 1, 1]]
    assert payload.drilldown == {"dimension": "seniority", "key": "seriesName"}
    assert payload.height == "128px"  # 24px per company row + 80px axis band


def test_company_categories_is_a_share_heatmap_over_all_nine_categories(tmp_path):
    payload = charts.company_categories(_seeded(tmp_path), "pharma", 0, now=NOW)
    option = payload.option
    categories = [c for c, _ in charts.analytics.CATEGORY_KEYWORDS] + ["Other"]
    assert option["xAxis"]["data"] == categories
    assert option["yAxis"]["data"] == ["MSD"]
    assert option["xAxis"]["axisLabel"]["rotate"] == 30
    assert option["xAxis"]["axisLabel"]["interval"] == 0     # show every category label
    assert option["visualMap"]["min"] == 0 and option["visualMap"]["max"] == 100
    cells = {(x, y): v for x, y, v in option["series"][0]["data"]}
    assert cells[(categories.index("Quality"), 0)] == 100.0
    assert cells[(categories.index("Other"), 0)] == 0.0
    assert payload.rows == [["MSD", "Quality", 2, 100.0]]  # only non-zero cells in the table
    assert payload.drilldown == {"dimension": "company", "key": "row"}


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
        "seniority-mix", "company-categories", "days-to-close",
    }
    for builder in charts.CHARTS.values():
        assert callable(builder)


from pathlib import Path


def test_palette_matches_base_html():
    html = (Path(__file__).resolve().parent.parent / "dashboard" / "templates" / "base.html").read_text()
    for value in charts.PALETTE.values():
        for hex_value in (value if isinstance(value, list) else [value]):
            assert hex_value in html, f"{hex_value} missing from base.html tokens"
