# Project Status

Last updated: 2026-05-25  
Last worked on: This machine (laptop 1)

---

## What this project is

A self-hosted dashboard to track Indian government scheme money from Union Budget → State → District → Officer.  
Core question: "₹X allocated for NREGA in Udaipur. Only ₹Y spent. DC [Name] was in charge. Where did the rest go?"

Stack: Python Flask (port 5000) + SQLite (`scheme_tracker.db`) + plain HTML/JS (port 3000). No React, no npm.

---

## Current state of the database

| Table | What's in it |
|---|---|
| `schemes` | 6 schemes: NREGA, PM-JAY, PM-KISAN, PMAY-U, PM Ujjwala, Jal Jeevan Mission |
| `financials` | 120 rows — state-level data for all 6 schemes, FY 2024-25 |
| `fund_flow` | 33 NREGA Rajasthan district rows with allocation, expenditure, KPIs. 0 block rows. |
| `officers` | 38 rows — 2 central, 3 state (CM + Principal Secretary + State Programme Coordinator), 33 district collectors (all Rajasthan) |

---

## What's working

- **Dashboard** (`dashboard.html`) — 6 tabs: Overview, Fund Utilization, Red Flags, State-wise, Money Trail, Rankings
- **Mind map** (`mindmap.html`) — D3 force-directed graph, expands: Scheme → State → District → Block (skeleton)
- **Money Trail** — NREGA Rajasthan fully wired: allocation vs expenditure, DC accountability, red flags per district
- **Rankings tab** — sortable by expenditure, utilization, completion %, avg wage, red flags — with DC names
- **All 6 schemes** have state-level financial data for FY 2024-25
- **NREGA Rajasthan** has full district-level data (33 districts, DC names, allocation gaps)
- **Red flag detection** — auto-detects low wage, low completion, low 100-day households

---

## What's half-done / known gaps

### Block-level data (next priority)
- Schema is ready in `fund_flow` (level='block')
- `scrape_blocks.py` is written and ready to run
- **Blocker:** nrega.nic.in has CAPTCHA on the citizen portal. The scraper is ready but the portal blocks automated access.
- **What to try:** Run `python3 scrape_blocks.py --district UDAIPUR` and see if CAPTCHA situation has changed. If it works, run for all 33 districts.
- Once blocks are scraped, the mind map auto-expands district → block nodes.

### Non-Rajasthan NREGA districts
- `fund_flow` only has Rajasthan. Other states (Bihar, UP etc.) show "no data" in mind map.
- `scrape_real_data.py` scrapes DeshSeva — can be extended to other states by changing the state filter.

### PM-KISAN can go to individual beneficiary level
- pmkisan.gov.in has public beneficiary list: State → District → Sub-district → Village → Individual farmer
- No login required. This is the only scheme where user-level drill-down is possible.
- Not yet built. Would need Playwright scraper + new DB table.

### JJM has no financial figures
- `ejalshakti.gov.in` only exposes tap connection counts, not ₹ allocation/expenditure
- Financials show NULL for JJM — just beneficiary (connection) count per state

---

## Files and what they do

| File | Purpose | Status |
|---|---|---|
| `scheme_tracker_backend.py` | Flask API, all endpoints | Active, authoritative |
| `dashboard.html` | Main dashboard frontend | Active, authoritative |
| `mindmap.html` | D3 mind map page | Active, authoritative |
| `scrape_schemes.py` | Scrapes JJM, PM-KISAN, PMAY-U, PM-JAY, Ujjwala | Done, re-run to refresh |
| `scrape_real_data.py` | Scrapes NREGA district data from DeshSeva | Done, re-run to refresh |
| `scrape_blocks.py` | Block-level NREGA scraper | Ready, blocked by CAPTCHA |
| `fetch_labour_budget.py` | Fetches approved labour budget → allocation ₹ | Done, re-run to refresh |
| `add_district_collectors.py` | Loads DC names for 33 Rajasthan districts | Done, idempotent |
| `load_sample_data.py` | Old sample data loader | Ignore — real data is in DB |

**Dead files (not in git, can delete):**
- `dashboard.jsx` — React prototype, replaced by `dashboard.html`
- `money_trail_api.py` — patch file, already merged into backend
- `COMPLETE_PACKAGE.txt`, `QUICK_START.md`, `SUMMARY.md` — stale auto-generated docs

---

## API endpoints (quick ref)

```
GET  /api/dashboard                          # summary stats
GET  /api/utilization?year=2024-25           # fund utilization by scheme+state
GET  /api/money-trail/RAJASTHAN              # all 33 NREGA districts
GET  /api/money-trail/RAJASTHAN/<district>   # district detail + red flags
GET  /api/money-trail/RAJASTHAN/<district>/blocks  # blocks (empty until scraped)
GET  /api/rankings?metric=expenditure        # district rankings
GET  /api/red-flags                          # auto-detected anomalies
GET  /api/mindmap/schemes                    # scheme aggregates for mind map
GET  /api/officers?state=RAJASTHAN&level=state  # officer lookup
```

---

## How to run

```bash
source ~/envs/evn_gov_schemes/bin/activate
python3 scheme_tracker_backend.py    # terminal 1 — API on :5000
python3 -m http.server 3000          # terminal 2 — open localhost:3000/dashboard.html
```

---

## Known bugs fixed (don't re-introduce)

- **NREGA year mismatch** — NREGA financials were year=`'2024'`, all other schemes use `'2024-25'`. Fixed by updating DB. If you re-run `scrape_real_data.py`, make sure it writes year=`'2024-25'`.
- **Duplicate scheme names** — old long-name schemes (e.g. "Pradhan Mantri Jan Arogya Yojana (PM-JAY)") used to co-exist with short names. Fixed. `init_default_schemes()` in backend now checks before inserting.
- **Mind map NREGA invisible** — caused by the year mismatch above + `expandState` was guarded by `if scheme === 'NREGA'`. Both fixed.

---

## What to work on next

1. **Try running `scrape_blocks.py`** — CAPTCHA may have changed. Start with one district.
2. **PM-KISAN beneficiary drill-down** — only scheme with public user-level data. Playwright scraper needed.
3. **More states for NREGA** — extend `scrape_real_data.py` to Bihar, UP, MP.
4. **Mind map UX** — loading spinner on nodes while async fetch runs, better "no data" visual.
