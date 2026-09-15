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

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import echartsy as ec

# Validated against the cream surface #FAF7F2 with the dataviz palette validator
# (spec §7). base.html carries the same hex values as CSS custom properties;
# tests/test_charts.py::test_palette_matches_base_html keeps them in sync.
PALETTE = {
    "bar": "#2F5D50",            # single-hue magnitude bars
    "pharma": "#1F7F5C",         # categorical slot 1 (Home velocity line)
    "tech": "#C46A1E",           # categorical slot 2
    "ordinal": ["#8FB5A2", "#659A84", "#417C66", "#2F5D50"],  # Junior -> Director
    "neutral": "#CFC6B8",        # Unspecified seniority
    "sequential": ["#DCE9E1", "#B5D0C2", "#8AB5A0", "#5F977F", "#3F7A63", "#2F5D50"],
    "grid": "#EFE9DF",           # hairline gridlines, one step off the surface
    "ink": "#22392F",
    "muted": "#8A7F6E",
    "border": "#E8E0D4",
}

SENIORITY_ORDER = ["Junior", "Senior", "Lead", "Director", "Unspecified"]


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


CHARTS: Dict[str, Callable] = {}
