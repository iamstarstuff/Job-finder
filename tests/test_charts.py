import pandas as pd

from dashboard import charts


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
