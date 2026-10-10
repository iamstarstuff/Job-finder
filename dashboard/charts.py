"""Chart builders: analytics rows -> echartsy Figure -> ECharts option.

No SQL here (that is jobfinder/analytics.py) and no Flask (that is
dashboard/app.py). Every builder returns a ChartPayload: the ECharts option
plus a table-view twin (columns + rows) and an optional drilldown descriptor,
matching docs/superpowers/specs/2026-09-15-dashboard-analytics-revamp-design.md §3.1.

echartsy rules learned during design (spec §3.2):
- never fig.title() -- the card's <h3> carries the title;
- never hue= for multi-series charts -- it sorts series alphabetically and
  ignores name=; add one series per call from a wide DataFrame instead, and
  name the y column what the tooltip should say;
- ItemStyle(border_radius=[0, 4, 4, 0]) passes a list through (rounded data end only);
- heatmap() drops rows whose value is None, so zero cells are given 0.0 (the
  lightest step, 1.2:1 against the surface) to keep both axes complete.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, Optional

import echartsy as ec
import pandas as pd

from jobfinder import analytics

# Validated against the cream surface #FAF7F2 with the dataviz palette validator
# (spec §7). base.html carries the same hex values as CSS custom properties;
# tests/test_charts.py::test_palette_matches_base_html keeps them in sync.
PALETTE = {
    "bar": "#2F5D50",            # single-hue magnitude bars
    "pharma": "#1F7F5C",         # categorical slot 1 (Home velocity line)
    "tech": "#C46A1E",           # categorical slot 2
    # Intern/Graduate -> Director+: one green hue, monotone lightness; light end 2.26:1 on the
    # surface (dataviz validate_palette.js --ordinal, 2026-10-10)
    "ordinal": ["#81B19B", "#6E9D88", "#5A8974", "#487662", "#356350", "#23513E", "#0F3F2E"],
    "neutral": "#CFC6B8",        # "Not stated" seniority
    "sequential": ["#DCE9E1", "#B5D0C2", "#8AB5A0", "#5F977F", "#3F7A63", "#2F5D50"],
    "grid": "#EFE9DF",           # hairline gridlines, one step off the surface
    "ink": "#22392F",
    "muted": "#8A7F6E",
    "border": "#E8E0D4",
}

SENIORITY_ORDER = analytics.SENIORITY_LEVELS   # Claude's levels; "Not stated" last, in the neutral colour


@dataclass
class ChartPayload:
    option: dict
    columns: List[str]
    rows: List[list]
    drilldown: Optional[dict] = None
    height: str = "360px"   # only the builder knows the row count, so it sizes the plot

    def to_dict(self) -> dict:
        return {"option": self.option, "columns": self.columns, "rows": self.rows,
                "drilldown": self.drilldown, "height": self.height}


def _empty(columns: List[str], drilldown: Optional[dict] = None) -> ChartPayload:
    """What a builder returns when the window holds no data: the client shows
    an empty-state line instead of mounting a plot."""
    return ChartPayload(option={}, columns=columns, rows=[], drilldown=drilldown)


def _figure(height: str = "360px", trigger: str = "axis", pointer: str = "shadow") -> ec.Figure:
    """A Figure with the page's chart chrome applied: SVG renderer, solid
    hairline gridlines one step off the surface, white tooltip in ink."""
    fig = ec.figure(height=height, renderer="svg")
    fig.grid(show=True, axis="both", style="solid", color=PALETTE["grid"])
    fig.margins(left=8, right=16, top=12, bottom=8)
    fig.tooltip(trigger=trigger, pointer=pointer, background_color="#FFFFFF",
                border_color=PALETTE["border"], text_color=PALETTE["ink"])
    return fig


def _bar_style() -> ec.ItemStyle:
    """Rounded data end only; square at the baseline (mark spec)."""
    return ec.ItemStyle(border_radius=[0, 4, 4, 0])


def _line_style() -> ec.LineStyle:
    return ec.LineStyle(width=2, cap="round", join="round")


def skills_in_demand(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.skill_demand(conn, sector=sector, weeks=weeks, limit=15, now=now)
    columns = ["Skill", "Roles"]
    drilldown = {"dimension": "skill", "key": "name"}
    if not rows:
        return _empty(columns, drilldown)
    # ECharts draws a category axis bottom-up: reverse so the biggest bar is on top.
    df = pd.DataFrame({"Skill": [r["skill"] for r in rows], "Roles": [r["count"] for r in rows]})[::-1]
    height = "420px"
    fig = _figure(height=height)
    fig.barh(df, x="Skill", y="Roles", color=PALETTE["bar"], barMaxWidth=20, item_style=_bar_style())
    fig.legend(show=False)
    return ChartPayload(fig.to_option(), columns, [[r["skill"], r["count"]] for r in rows], drilldown, height)


def hiring_velocity(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    fig = _figure(pointer="line")
    if sector:
        rows = analytics.new_jobs_per_week(conn, weeks=weeks, sector=sector, now=now)
        columns = ["Week", "New jobs"]
        if not rows:
            return _empty(columns)
        df = pd.DataFrame({"Week": [analytics.week_label(r["week"]) for r in rows],
                           "New jobs": [r["count"] for r in rows]})
        fig.plot(df, x="Week", y="New jobs", color=PALETTE["bar"], area=True, area_opacity=0.10,
                 symbol_size=8, line_style=_line_style())
        fig.legend(show=False)
        return ChartPayload(fig.to_option(), columns, [[r["week"], r["count"]] for r in rows])
    pharma = {r["week"]: r["count"] for r in analytics.new_jobs_per_week(conn, weeks=weeks, sector="pharma", now=now)}
    tech = {r["week"]: r["count"] for r in analytics.new_jobs_per_week(conn, weeks=weeks, sector="tech", now=now)}
    all_weeks = sorted(set(pharma) | set(tech))
    columns = ["Week", "Pharma", "Tech"]
    if not all_weeks:
        return _empty(columns)
    df = pd.DataFrame({"Week": [analytics.week_label(w) for w in all_weeks],
                       "Pharma": [pharma.get(w, 0) for w in all_weeks],
                       "Tech": [tech.get(w, 0) for w in all_weeks]})
    for name, color in (("Pharma", PALETTE["pharma"]), ("Tech", PALETTE["tech"])):
        fig.plot(df, x="Week", y=name, color=color, symbol_size=8, line_style=_line_style(),
                 end_label=ec.EndLabelStyle(show=True, formatter="{a}", color=PALETTE["ink"]))
    fig.legend(show=True, left="left", top=0)
    return ChartPayload(fig.to_option(), columns,
                        [[w, pharma.get(w, 0), tech.get(w, 0)] for w in all_weeks])


def who_is_hiring(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.company_velocity(conn, sector=sector, weeks=weeks, now=now)
    columns = ["Company", "Open roles", "New in window", "New in previous window"]
    drilldown = {"dimension": "company", "key": "name"}
    top = [r for r in rows if r["active"] > 0][:15]
    if not top:
        return _empty(columns, drilldown)
    df = pd.DataFrame({"Company": [r["company"] for r in top],
                       "Open roles": [r["active"] for r in top]})[::-1]
    height = f"{24 * len(top) + 80}px"
    fig = _figure(height=height)
    fig.barh(df, x="Company", y="Open roles", color=PALETTE["bar"], barMaxWidth=20, item_style=_bar_style())
    fig.legend(show=False)
    table = [[r["company"], r["active"], r["new_in_window"],
              "" if r["new_previous_window"] is None else r["new_previous_window"]] for r in rows]
    return ChartPayload(fig.to_option(), columns, table, drilldown, height)


def _share(count: int, total: int) -> float:
    return round(100.0 * count / total, 1) if total else 0.0


def skill_trend(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.skill_shares_by_week(conn, sector=sector, weeks=weeks, limit=12, now=now)
    columns = ["Week", "Skill", "Roles needing it", "Roles read that week", "Share %"]
    drilldown = {"dimension": "skill", "key": "row"}
    if not rows:
        return _empty(columns, drilldown)
    skills = list(dict.fromkeys(r["skill"] for r in rows))       # top-first, as analytics returns them
    by_skill = {s: [r for r in rows if r["skill"] == s] for s in skills}
    # Build skill-major with the top skill LAST so it renders at the top of the y axis;
    # zero cells are 0.0 (not None) so echartsy keeps both axes complete (see module docstring).
    cells = [{"Week": analytics.week_label(r["week"]), "Skill": s, "Share": _share(r["count"], r["total"])}
             for s in reversed(skills) for r in by_skill[s]]
    df = pd.DataFrame(cells)
    height = f"{28 * len(skills) + 90}px"
    fig = _figure(height=height, trigger="item")
    fig.heatmap(df, x="Week", y="Skill", value="Share", in_range_colors=PALETTE["sequential"],
                label_show=False, visual_min=0, visual_max=float(max(df["Share"].max(), 1.0)))
    week_labels = list(dict.fromkeys(r["week"] for r in rows))
    step = max(0, len(week_labels) // 14)
    fig.xticks(interval=step, rotate=45)
    table = [[r["week"], r["skill"], r["count"], r["total"], _share(r["count"], r["total"])] for r in rows]
    return ChartPayload(fig.to_option(), columns, table, drilldown, height)


def _company_order(totals: Counter) -> List[str]:
    """Companies by total desc, then name -- the display order (top first)."""
    return [c for c, _ in sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))]


def seniority_mix(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.seniority_counts(conn, sector=sector, weeks=weeks, now=now)
    columns = ["Company"] + SENIORITY_ORDER + ["Roles read"]
    drilldown = {"dimension": "seniority", "key": "seriesName"}
    if not rows:
        return _empty(columns, drilldown)
    counts: Dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    for r in rows:
        counts[r["company"]][r["seniority"]] += r["count"]
        totals[r["company"]] += r["count"]
    companies = _company_order(totals)
    bottom_up = companies[::-1]
    df = pd.DataFrame({"Company": bottom_up})
    for tier in SENIORITY_ORDER:
        df[tier] = [_share(counts[c][tier], totals[c]) for c in bottom_up]
    height = f"{24 * len(companies) + 80}px"
    fig = _figure(height=height)
    colors = PALETTE["ordinal"] + [PALETTE["neutral"]]
    for tier, color in zip(SENIORITY_ORDER, colors):
        # a 2px surface-coloured border is the "surface gap" between stacked segments
        fig.barh(df, x="Company", y=tier, stack=True, color=color, barMaxWidth=20,
                 item_style=ec.ItemStyle(border_color="#FFFFFF", border_width=2))
    fig.extra(xAxis={"type": "value", "min": 0, "max": 100, "axisLabel": {"formatter": "{value}%"}})
    fig.legend(show=True, left="left", top=0)
    table = [[c] + [counts[c][t] for t in SENIORITY_ORDER] + [totals[c]] for c in companies]
    return ChartPayload(fig.to_option(), columns, table, drilldown, height)


def company_families(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.family_counts(conn, sector=sector, weeks=weeks, now=now)
    columns = ["Company", "Role family", "Roles", "Share %"]
    drilldown = {"dimension": "company_family", "key": "cell"}
    if not rows:
        return _empty(columns, drilldown)
    by: Dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    family_totals: Counter = Counter()
    for r in rows:
        by[r["company"]][r["family"]] += r["count"]
        totals[r["company"]] += r["count"]
        family_totals[r["family"]] += r["count"]
    companies = _company_order(totals)
    families = _company_order(family_totals)   # same rule: largest first, then name
    cells = [{"Role family": f, "Company": c, "Share": _share(by[c][f], totals[c])}
             for c in companies[::-1] for f in families]
    df = pd.DataFrame(cells)
    height = f"{28 * len(companies) + 90}px"
    fig = _figure(height=height, trigger="item")
    fig.heatmap(df, x="Role family", y="Company", value="Share", in_range_colors=PALETTE["sequential"],
                label_show=False, visual_min=0, visual_max=100)
    fig.xticks(interval=0, rotate=30)
    table = [[c, f, by[c][f], _share(by[c][f], totals[c])]
             for c in companies for f in families if by[c][f]]
    return ChartPayload(fig.to_option(), columns, table, drilldown, height)


def days_to_close(conn, sector: Optional[str], weeks: int, now: Optional[datetime] = None) -> ChartPayload:
    rows = analytics.median_days_active(conn, sector=sector, weeks=weeks, min_closed=3, now=now)
    columns = ["Company", "Median days open", "Closed jobs"]
    drilldown = {"dimension": "company", "key": "name"}
    if not rows:
        return _empty(columns, drilldown)
    rows = sorted(rows, key=lambda r: (-r["median_days"], r["company"]))
    df = pd.DataFrame({"Company": [r["company"] for r in rows],
                       "Median days open": [r["median_days"] for r in rows]})[::-1]
    height = f"{24 * len(rows) + 80}px"
    fig = _figure(height=height)
    fig.barh(df, x="Company", y="Median days open", color=PALETTE["bar"], barMaxWidth=20, item_style=_bar_style())
    fig.legend(show=False)
    return ChartPayload(fig.to_option(), columns,
                        [[r["company"], r["median_days"], r["closed"]] for r in rows], drilldown, height)


CHARTS: Dict[str, Callable] = {}

CHARTS.update({
    "skills-in-demand": skills_in_demand,
    "hiring-velocity": hiring_velocity,
    "who-is-hiring": who_is_hiring,
    "skill-trend": skill_trend,
})

CHARTS.update({
    "seniority-mix": seniority_mix,
    "company-families": company_families,
    "days-to-close": days_to_close,
})
