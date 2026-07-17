// Generic click-to-drilldown for the Analytics page's bar/doughnut charts.
// Fetches the jobs behind a clicked chart element from
// /api/drilldown/<dimension>?value=<value> and renders them into a
// collapsible panel below the chart. Shared across every chart on the page
// rather than duplicated per chart.

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = String(str);
  return div.innerHTML;
}

// escapeHtml() only escapes &, <, > (text-node context) — it does not
// escape quote characters, so it is unsafe to use directly inside an HTML
// attribute value (e.g. href="..."). A url containing a bare double quote
// could otherwise break out of the attribute and inject markup. Also
// restrict to http(s) so a scraped url can't smuggle a javascript: link.
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function isSafeUrl(url) {
  return /^https?:\/\//i.test(url);
}

function closeDrilldownPanel(panel) {
  panel.classList.add("hidden");
  panel.innerHTML = "";
}

function renderDrilldownPanel(panel, value, rows) {
  const closeBtn = '<button class="drilldown-close" type="button">Close ✕</button>';
  if (!rows.length) {
    panel.innerHTML = closeBtn + "<p>No jobs found for “" + escapeHtml(value) + "”.</p>";
  } else {
    const rowsHtml = rows.map(function (r) {
      const applyLink = (r.url && isSafeUrl(r.url))
        ? '<a class="btn" href="' + escapeAttr(r.url) + '" target="_blank" rel="noopener">Apply</a>'
        : "";
      return "<tr><td>" + escapeHtml(r.company) + "</td><td>" + escapeHtml(r.title) +
        "</td><td>" + escapeHtml(r.first_seen.slice(0, 10)) + "</td><td>" + applyLink + "</td></tr>";
    }).join("");
    panel.innerHTML = closeBtn +
      "<h4>" + rows.length + " job" + (rows.length === 1 ? "" : "s") + " — " + escapeHtml(value) + "</h4>" +
      "<table><tr><th>Company</th><th>Title</th><th>First seen</th><th></th></tr>" + rowsHtml + "</table>";
  }
  panel.querySelector(".drilldown-close").onclick = function () { closeDrilldownPanel(panel); };
  panel.classList.remove("hidden");
}

async function loadDrilldown(panel, dimension, value) {
  panel.classList.remove("hidden");
  panel.innerHTML = "<p>Loading…</p>";
  const url = "/api/drilldown/" + encodeURIComponent(dimension) + "?value=" + encodeURIComponent(value);
  const resp = await fetch(url);
  const rows = await resp.json();
  renderDrilldownPanel(panel, value, rows);
}

// Returns a Chart.js `options.onClick` handler bound to one panel/dimension.
// `labelFn(element, chart)` extracts the drilldown value (e.g. a company or
// skill name) from the clicked chart element. Clicking the same value again
// closes the panel instead of re-fetching.
function makeDrilldownHandler(panelId, dimension, labelFn) {
  const panel = document.getElementById(panelId);
  let openValue = null;
  return function (event, elements, chart) {
    if (!elements.length) return;
    const value = labelFn(elements[0], chart);
    if (openValue === value) {
      closeDrilldownPanel(panel);
      openValue = null;
      return;
    }
    openValue = value;
    loadDrilldown(panel, dimension, value);
  };
}
