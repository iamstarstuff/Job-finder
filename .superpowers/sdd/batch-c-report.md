# Batch C report: Alkermes, Teva, Viatris, Grifols, Leo Pharma, ICON + Alexion coverage check

Status: DONE (6 of 6 registered; 0 skipped)

Baseline: `python -m pytest tests/ -q` → 59 passed.
Final: `python -m pytest tests/ -q` → 73 passed (14 new tests, 0 skipped/broken).

## 1. Alkermes (Oracle Recruiting Cloud — not on the brief's discovery list at all)

- `GET https://www.alkermes.com/careers` → `HTTP 200`, no ATS markers in the HTML. It links to `https://careers.alkermes.com/`, which is a thin loader page (`<body onload="replacecontent()">`) whose inline JS reads `const host = 'https://hbap.fa.us1.oraclecloud.com'` and redirects into `/hcmUI/CandidateExperience/...` — Oracle Recruiting Cloud (Fusion HCM Candidate Experience), not Workday/Phenom/Eightfold/Avature/SmartRecruiters/Cornerstone/iCIMS.
- Its REST API is callable anonymously: `GET https://hbap.fa.us1.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList&finder=findReqs;siteNumber=CX_1,facetsList=LOCATIONS,limit=25,offset=0,selectedLocationsFacet=300000000191040`
- The `LOCATIONS` facet's country-level breakdown was fetched once unfiltered to find Ireland's facet id: `300000000191040` (verified live: 2 hits, both Dublin, out of 74 total Alkermes jobs globally).
- Job detail URL pattern confirmed live: `https://hbap.fa.us1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/{Id}` (HTTP 200).
- Live result: **2 jobs**. Sample titles:
  1. Lead, GMP Auditor
  2. Sr Financial Analyst
- (Only 2 titles exist live — both sampled above.)

## 2. Teva (Eightfold — same ATS family as `bms()`, different endpoint)

- `GET https://www.tevapharm.com/careers/` → `HTTP 404`; the real career-hub link on `https://www.tevapharm.com/your-career/` points to `https://www.careers.teva/` (Eightfold-hosted, confirmed via `Sentry.setTag("product", "pcs")` and `/gen/js/ef-*.js` bundle names).
- `bms()`'s endpoint (`/api/pcsx/search?domain=...`) returns `HTTP 403 {"message": "PCSX is not enabled for this user."}` for this domain — a real, reproducible block, not transient (retried 3x).
- The underlying Eightfold widget itself calls a different endpoint that works anonymously: `GET https://www.careers.teva/api/apply/v2/jobs?domain=tevapharm.com&query=&location=Ireland&start=0` → `HTTP 200`, JSON with a `positions` array and `count` total (same shape family as `bms()`'s `data.positions`/`data.count`, just a flatter envelope and a `canonicalPositionUrl` field that's already an absolute listing-page URL).
- Live result: **3 jobs**, all Waterford (matches the brief's guess). Sample titles:
  1. Associate Director Global Quality Compliance TORCH
  2. Assoc Dir Global Category Manager Devices
  3. Site Microbiologist

## 3. Viatris (Workday — confirmed, with a live pagination-total bug worth flagging)

- `GET https://www.viatris.ie/en-ie/careers` → `HTTP 200`, links directly to `https://viatris.wd5.myworkdayjobs.com/External?Country=04a05835925f45b3a59406a2a6b72c8a` (the Ireland GUID is baked into the site's own link).
- `POST .../wday/cxs/viatris/External/jobs` with `appliedFacets: {"Location_Country": [...]}` (the key `pfizer()`/`gilead()` use) → `HTTP 400` every time. The tenant's own unfiltered `facets` response names the field `"Country"` (not `"Location_Country"`); switching the key to `"Country"` → `HTTP 200`, 61 Ireland hits.
- **Live pagination bug found and worked around**: this tenant's `total` field is only reliable on page 1. Verified live: page 2 (`offset=20`) reports `total: 0` while `jobPostings` keeps returning real results; continuing to page past the true end (`offset=61`) wraps back around to page-1 content with `total: 61` again (an infinite-loop trap if the loop keeps trusting each page's `total`). Fix: cache `total` from the *first* response only and never re-read it on later pages. Confirmed this yields exactly 61 unique job URLs (verified via `set()` dedup) where the naive "trust every page's total" version stopped early at 40.
- Live result: **61 jobs**. Sample titles:
  1. Manufacturing Operator ( 6 Months Agency Contract )
  2. Director Global Regulatory Compliance (Process Excellence)
  3. Head of External Sterile Operations (Anywhere in Europe)
  - (Note: some results are "Anywhere in Europe" / remote-eligible postings that the tenant itself tags with the Ireland country facet because Dublin is a listed option among several; left as-is per the existing codebase's convention of trusting the ATS's own country facet rather than re-deriving location from free text.)

## 4. Grifols (SAP SuccessFactors "job2web" — server-rendered HTML, new platform for this codebase)

- `GET https://www.grifols.com/en/careers` → `HTTP 200`, links to `https://jobsearch.grifols.com/`, a legacy SuccessFactors career-site-builder (`successfactors.com`/`successfactors.eu` asset hosts, "job2web" CSS bundle names).
- Search page: `GET https://jobsearch.grifols.com/search/?q=&locationsearch=Ireland&startrow=0` → `HTTP 200`, server-rendered `<table id="searchresults">` with `<tr class="data-row">` rows (same shape used for `apc()`, adapted for SuccessFactors' markup) and a `<span class="paginationLabel">Results <b>1 – 7</b> of <b>7</b></span>` total marker.
- **Pagination gotcha discovered and handled**: requesting `startrow` at or past the filtered total silently drops the `locationsearch` filter and returns an unrelated default job list (verified live: `startrow=7` — exactly the Ireland total — returned different, non-Ireland jobs). The scraper stops via the parsed total (`offset < total`) rather than "loop while any rows returned," so it never issues that boundary-crossing request.
- Live result: **7 jobs**, all Dublin. Sample titles:
  1. Site Procurement Senior Specialist
  2. Calibration Engineer
  3. Clinical Research Associate

## 5. Leo Pharma (same SuccessFactors platform as Grifols — currently zero live Ireland roles)

- `GET https://www.leo-pharma.com/careers` → `HTTP 404`; real link is `https://www.leo-pharma.com/your-career/jobs` → `https://jobs.leo-pharma.com/`, the identical SuccessFactors job2web platform as Grifols (same CSS bundle paths, same `data-row`/`jobTitle-link`/`paginationLabel` markup).
- `GET https://jobs.leo-pharma.com/search/?q=&locationsearch=Ireland` (and `Dublin`, `Cork`, `IE` variants) → `HTTP 200` but the results table is omitted entirely (no `paginationLabel`, no `data-row`) — the real observed "zero results" shape, distinct from a normal small-result page.
- To confirm this wasn't a location-string mismatch, scanned every live LEO Pharma posting globally (5 pages, ~110 jobs at `q=` with no filter) and collected every job's location field — no entry contains "Ireland" (locations span Denmark, France, US, Canada, Brazil, Poland, UK, etc., but not Ireland/Dublin/Cork).
- Registered anyway (this is a working pattern, not a block) — it will start surfacing results automatically the moment Leo Pharma opens an Irish role.
- Live result: **0 jobs** (confirmed correct — not an error). No sample titles available since none currently exist.

## 6. ICON plc (server-rendered Attrax, same platform as `abbvie()` — "powered by SmartRecruiters" per its own footer, but needs its own location strategy)

- `GET https://careers.iconplc.com` → `HTTP 200`, same Attrax widget classes (`attrax-search-widget`, `attrax-vacancy-tile__title`) as `abbvie()`, footer literally says "Site powered by SmartRecruiters" (ICON uses SmartRecruiters as the backend ATS behind an Attrax-branded front end).
- `abbvie()`'s geo-radius pattern (`?q=&options=&page=1&la=<lat>&lo=<lon>&ln=Dublin,%20Ireland&lr=100`) returns **zero results** for ICON even centered exactly on Dublin — verified live, the page renders an explicit "no results" message. ICON posts globally across 53 countries and Ireland doesn't appear in the default location-facet sidebar (which only surfaces top regions by count).
- Fallback: the site's own keyword search, `?q=Ireland&page=N`, does surface every genuine Ireland posting — but also real noise, verified live: Northern Ireland roles (UK jobs, e.g. `.../site-payment-analyst-in-regional-great-britain-northern-ireland-jid-51915`) and jobs with no Ireland location at all whose *descriptions* merely mention Ireland (e.g. two Reading, UK and Warsaw, Poland roles appeared on page 4 with zero "ireland" substring anywhere in their own URL slugs).
- **Filter used**: every genuine Republic-of-Ireland posting's own URL slug contains the literal substring `-in-ireland-` (e.g. `.../contract-analyst-i-in-ireland-dublin-jid-52013`); Northern Ireland postings use `-northern-ireland-` instead (no `-in-` immediately before `ireland`), and the pure-noise matches have no "ireland" substring in their slug at all. Filtering on `-in-ireland-` in the href — not on keyword-search relevance — cleanly separates real Dublin hits from both categories of noise (manually verified: 42 raw hits across `q=Ireland`'s 4 pages narrowed to 31 genuine ones).
- Live result: **31 jobs**, all Dublin. Sample titles:
  1. Senior HR Regional Manager - Ireland & UK
  2. Contract Analyst I
  3. Principal Auditor, Quality Assurance - CSV, AI & Risk Assessment

## Alexion (AstraZeneca) coverage check

**Finding: already covered by the existing `astrazeneca()` scraper — no new scraper needed.**

- `astrazeneca(build_session())` currently returns 11 Dublin jobs; none are Alexion-branded (grepped titles/URLs for "alexion" — zero matches).
- However, Alexion postings genuinely live on the *same* `careers.astrazeneca.com` site/ATS: a keyword search there, `GET https://careers.astrazeneca.com/search-jobs/alexion`, returns 15 real Alexion-branded postings (e.g. "Alexion - Head of Finance", "Country Study Manager (Alexion)", "Senior Product Manager (Alexion)") using the exact same `search-results-link` tile markup the existing scraper already parses — confirming Alexion isn't a separate site/tenant that got missed, it's the same infrastructure the scraper already crawls.
- `https://alexion.com/careers` and `https://www.alexion.com/careers` both `404` (verified live) — there is no independent Alexion careers site/tenant to add a scraper for, consistent with Alexion having been folded into AstraZeneca's own careers infrastructure.
- Conclusion: the reason today's Ireland-filtered `astrazeneca()` output has 0 Alexion hits is simply that Alexion currently has no open Ireland roles (College Park Dublin / Athlone) right now — not a coverage gap. The moment Alexion posts an Ireland role on careers.astrazeneca.com, the existing country-facet-filtered scraper will pick it up automatically. No code change made.

## Self-review checklist

- [x] Registry keys match the brief exactly, appended after `"GSK"`: `"Alkermes"`, `"Teva"`, `"Viatris"`, `"Grifols"`, `"Leo Pharma"`, `"ICON"`.
- [x] Every registered job URL absolute (`https://...`) — verified via live run for all six.
- [x] No `/apply` suffixes in any of the six scrapers' output — none of these ATS's listing-page URLs carry one (verified live for all six).
- [x] Ireland-only filtering effective for every company, ICON especially: ICON's raw keyword search is filtered down from 42 hits to 31 by requiring `-in-ireland-` in the URL slug, explicitly excluding Northern Ireland and description-only mentions. Viatris/Alkermes use the ATS's own country/location facet ID. Grifols/Leo Pharma use `locationsearch=Ireland` with total-bounded pagination (not "any rows returned", since past-total requests silently drop the filter).
- [x] No swallowed exceptions — all six scrapers use `fetch()` exclusively (raises via `response.raise_for_status()`), no `try/except` added.
- [x] Python 3.9 compatible — `python3 -c "import ast; ast.parse(open('jobfinder/scrapers.py').read())"` clean; no walrus/match/`X | None` syntax used.
- [x] Fixture route ordering checked for Grifols/Leo Pharma (`startrow=2` vs `startrow=0`) and ICON (`page=2` vs `page=1`): none of these pairs are string-prefixes of each other (they diverge in the final digit), so ordering can't cause a Batch-A-style collision, but the more-specific/later route is still listed first in each fixture dict for consistency with the codebase's established convention.
- [x] All six companies registered — no skipped/blocked companies this batch, so no dead code to check for.
- [x] Viatris pagination-total bug: caught via live verification (naive version returned 40/61 jobs), fixed by caching `total` from the first response only, re-verified live afterward (61/61, confirmed via URL dedup).

## Live verification commands run

```
python3 -c "
from jobfinder.http_client import build_session
from jobfinder import scrapers
session = build_session()
for name, fn in [
    ('Alkermes', scrapers.alkermes),
    ('Teva', scrapers.teva),
    ('Viatris', scrapers.viatris),
    ('Grifols', scrapers.grifols),
    ('Leo Pharma', scrapers.leo_pharma),
    ('ICON', scrapers.icon),
]:
    jobs = fn(session)
    print(name, len(jobs))
"
```
Output: Alkermes 2, Teva 3, Viatris 61, Grifols 7, Leo Pharma 0, ICON 31.

```
python3 -c "
from jobfinder.http_client import build_session
from jobfinder import scrapers
session = build_session()
jobs = scrapers.astrazeneca(session)
print(len(jobs), [j.title for j in jobs if 'alexion' in j.title.lower()])
"
```
Output: `11 []` — 11 total Ireland jobs, none Alexion-branded (confirming Alexion coverage finding above).
