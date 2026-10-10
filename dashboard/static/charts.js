// Mounts every [data-chart] card on the page: fetches its ECharts option from
// /api/charts/<name>?sector=&weeks= (plus the card's own select[data-param]
// choices), renders it with echarts (SVG), fills the "Show data" table, shows
// the payload's note, and wires click-to-drilldown through /api/drilldown/<dimension>.
// Every string from the API reaches the DOM through textContent -- no markup concatenation.
(function () {
  "use strict";

  function isSafeUrl(url) {
    return /^https?:\/\//i.test(url);
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function renderTable(container, columns, rows) {
    container.replaceChildren();
    if (!rows.length) {
      container.appendChild(el("p", "empty-note", "No data for this window."));
      return;
    }
    const table = el("table");
    const head = el("tr");
    columns.forEach((c) => head.appendChild(el("th", null, c)));
    table.appendChild(head);
    rows.forEach((r) => {
      const tr = el("tr");
      r.forEach((v) => tr.appendChild(el("td", null, v === null ? "" : v)));
      table.appendChild(tr);
    });
    container.appendChild(table);
  }

  function closePanel(panel) {
    panel.hidden = true;
    panel.replaceChildren();
  }

  function showDrilldownError(panel) {
    panel.replaceChildren();
    const close = el("button", "drilldown-close", "Close");
    close.type = "button";
    close.addEventListener("click", () => closePanel(panel));
    panel.appendChild(close);
    panel.appendChild(el("p", "empty-note", "Could not load the roles behind this value."));
    panel.hidden = false;
  }

  function renderDrilldown(panel, value, jobs) {
    panel.replaceChildren();
    const close = el("button", "drilldown-close", "Close");
    close.type = "button";
    close.addEventListener("click", () => closePanel(panel));
    panel.appendChild(close);
    const label = value.replace("::", " · ");
    if (!jobs.length) {
      panel.appendChild(el("p", "empty-note", "No jobs found for " + label + "."));
      panel.hidden = false;
      return;
    }
    panel.appendChild(el("h4", null, jobs.length + (jobs.length === 1 ? " job" : " jobs") + " for " + label));
    const wrap = el("div", "table-scroll");
    const table = el("table");
    const head = el("tr");
    ["Company", "Title", "First seen", ""].forEach((c) => head.appendChild(el("th", null, c)));
    table.appendChild(head);
    jobs.forEach((job) => {
      const tr = el("tr");
      tr.appendChild(el("td", null, job.company));
      tr.appendChild(el("td", "wrap", job.title));
      tr.appendChild(el("td", null, (job.first_seen || "").slice(0, 10)));
      const cell = el("td");
      if (job.url && isSafeUrl(job.url)) {
        const link = el("a", "btn", "Apply");
        link.href = job.url;           // a DOM property, not markup: no attribute escaping needed
        link.target = "_blank";
        link.rel = "noopener";
        cell.appendChild(link);
      }
      tr.appendChild(cell);
      table.appendChild(tr);
    });
    wrap.appendChild(table);
    panel.appendChild(wrap);
    panel.hidden = false;
  }

  // The card's own choices (e.g. What to learn's role families and levels) as
  // repeatable query parameters; they scope both the chart and its drilldowns.
  function cardParams(card) {
    const params = [];
    card.querySelectorAll("select[data-param]").forEach((select) => {
      Array.from(select.selectedOptions).forEach((option) => params.push([select.dataset.param, option.value]));
    });
    return params;
  }

  async function loadDrilldown(panel, dimension, value, card) {
    panel.hidden = false;
    panel.replaceChildren(el("p", "empty-note", "Loading…"));
    const params = new URLSearchParams({ value: value });
    params.set("weeks", card.dataset.weeks || "12");
    if (card.dataset.sector) params.set("sector", card.dataset.sector);
    cardParams(card).forEach(([name, v]) => params.append(name, v));
    try {
      const resp = await fetch("/api/drilldown/" + encodeURIComponent(dimension) + "?" + params.toString());
      if (!resp.ok) {
        showDrilldownError(panel);
        return;
      }
      renderDrilldown(panel, value, await resp.json());
    } catch (err) {
      showDrilldownError(panel);
    }
  }

  // Which field of the ECharts click event carries the drilldown value (spec §3.1;
  // "row" is a heatmap's y-category, "cell" its "row::column" pair).
  function clickValue(params, drilldown, option) {
    if (drilldown.key === "seriesName") return params.seriesName;
    if (drilldown.key === "row") return option.yAxis.data[params.value[1]];
    if (drilldown.key === "cell") return option.yAxis.data[params.value[1]] + "::" + option.xAxis.data[params.value[0]];
    return params.name;
  }

  function showEmpty(plot, text) {
    plot.style.height = "";
    plot.replaceChildren(el("p", "empty", text));
  }

  async function mount(card) {
    const plot = card.querySelector(".chart");
    let note = card.querySelector(".chart-note");
    if (!note) {
      note = el("p", "chart-note");
      plot.after(note);
    }
    note.textContent = "";
    if (card._chart) {
      card._chart.dispose();
      card._chart = null;
    }
    closePanel(card.querySelector(".drilldown"));
    const query = new URLSearchParams({ sector: card.dataset.sector || "", weeks: card.dataset.weeks || "12" });
    cardParams(card).forEach(([name, v]) => query.append(name, v));
    try {
      const resp = await fetch("/api/charts/" + encodeURIComponent(card.dataset.chart) + "?" + query.toString());
      if (!resp.ok) {
        showEmpty(plot, "This chart could not be loaded.");
        return;
      }
      const payload = await resp.json();
      renderTable(card.querySelector(".chart-table"), payload.columns, payload.rows);
      if (!payload.option || !Object.keys(payload.option).length) {
        showEmpty(plot, payload.note || "No data for this window.");
        return;
      }
      note.textContent = payload.note || "";
      plot.replaceChildren();
      plot.style.height = payload.height;
      const chart = echarts.init(plot, null, { renderer: "svg" });
      card._chart = chart;
      chart.setOption(payload.option);
      if (payload.drilldown) {
        const panel = card.querySelector(".drilldown");
        let open = null;
        chart.on("click", (params) => {
          const value = clickValue(params, payload.drilldown, payload.option);
          if (value === undefined || value === null) return;
          if (!panel.hidden && open === value) {
            closePanel(panel);
            open = null;
            return;
          }
          open = value;
          loadDrilldown(panel, payload.drilldown.dimension, value, card);
        });
      }
      if (!card._resizeObserved) {
        new ResizeObserver(() => card._chart && card._chart.resize()).observe(plot);
        card._resizeObserved = true;
      }
    } catch (err) {
      showEmpty(plot, "This chart could not be loaded.");
    }
  }

  document.querySelectorAll("[data-chart]").forEach((card) => {
    mount(card);
    card.querySelectorAll("select[data-param]").forEach((select) => {
      select.addEventListener("change", () => mount(card));
    });
  });
})();
