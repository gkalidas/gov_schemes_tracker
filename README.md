# Government Scheme Transparency Tracker

Track where public money goes — from Union Budget allocation down to the District Collector responsible for spending it.

**Core question:** ₹X was allocated for NREGA in Udaipur. Only ₹Y was spent. The District Collector [Name] was in charge. Where did the rest go?

---

## What's inside

| File | Purpose |
|---|---|
| `scheme_tracker_backend.py` | Flask API server (port 5000) |
| `dashboard.html` | Main dashboard — Overview, Fund Utilization, Red Flags, Money Trail, Rankings, PM-KISAN |
| `mindmap.html` | Interactive force-directed mind map — drill from scheme → state → district → block |
| `scheme_tracker.db` | SQLite database with real scraped data |
| `scrape_schemes.py` | Scrapes JJM, PM-KISAN, PMAY-U, PM-JAY, PM Ujjwala from govt portals |
| `scrape_real_data.py` | Scrapes NREGA district data for all 33 Rajasthan districts |
| `scrape_pmkisan.py` | PM-KISAN beneficiary scraper — State → District → Sub-district → Village → Farmer |
| `scrape_blocks.py` | Block-level NREGA scraper (ready — awaiting portal access) |
| `fetch_labour_budget.py` | Fetches approved labour budget (person-days → ₹ allocation) |
| `fetch_news.py` | Google News RSS fetcher — scheme + district/state news, cached in DB |
| `fetch_social.py` | Reddit + YouTube fetcher — social sentiment per scheme/district |
| `add_district_collectors.py` | Loads District Collector names for all 33 Rajasthan districts |

## Schemes tracked

| Scheme | Ministry | Data depth |
|---|---|---|
| NREGA | Rural Development | State → 33 Rajasthan districts (with DC names) |
| PM-JAY | Health & Family Welfare | 20 states |
| PM-KISAN | Agriculture | 20 states + district → sub-district → village → individual farmer |
| PMAY-U | Housing & Urban Affairs | 20 states |
| PM Ujjwala | Petroleum & Natural Gas | 20 states |
| Jal Jeevan Mission | Jal Shakti | 34 states (coverage % + tap connections) |

---

## Setup

### 1. Clone

```bash
git clone <repo-url>
cd gov_schemes_tracker
```

### 2. Create and activate virtual environment

```bash
python3 -m venv ~/envs/evn_gov_schemes
source ~/envs/evn_gov_schemes/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

> `playwright install chromium` downloads ~300MB. Required only for the scrapers — not needed just to run the dashboard.

### 4. Run

Open two terminals (both with venv activated):

**Terminal 1 — API server:**
```bash
source ~/envs/evn_gov_schemes/bin/activate
python3 scheme_tracker_backend.py
# Runs on http://localhost:5000
```

**Terminal 2 — Frontend:**
```bash
python3 -m http.server 3000
# Open http://localhost:3000/dashboard.html
# Mind map: http://localhost:3000/mindmap.html
```

---

## Re-scraping data

The DB in the repo already has real data for FY 2024-25. Run these only if you want fresh data:

```bash
source ~/envs/evn_gov_schemes/bin/activate

# NREGA — all 33 Rajasthan districts
python3 scrape_real_data.py

# Approved labour budget (allocation figures)
python3 fetch_labour_budget.py

# Other 5 schemes (JJM, PM-KISAN, PMAY-U, PM-JAY, PM Ujjwala)
python3 scrape_schemes.py

# District Collector names
python3 add_district_collectors.py

# PM-KISAN beneficiaries — full drill-down to individual farmers
python3 scrape_pmkisan.py
python3 scrape_pmkisan.py --resume        # resume an interrupted run
python3 scrape_pmkisan.py --workers 4     # parallel sub-district scrapers

# News and social (cached in DB, also refreshable live from the dashboard)
python3 fetch_news.py
python3 fetch_social.py

# Single district block test
python3 scrape_blocks.py --district UDAIPUR
```

---

## API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/dashboard` | Summary stats (schemes, datapoints, beneficiaries) |
| `GET /api/utilization?year=2024-25` | Fund utilization by scheme + state |
| `GET /api/money-trail/RAJASTHAN` | All 33 NREGA districts with DC names |
| `GET /api/money-trail/RAJASTHAN/<district>` | District detail + red flags |
| `GET /api/money-trail/RAJASTHAN/<district>/blocks` | Block-level data |
| `GET /api/rankings?metric=expenditure` | District rankings by metric |
| `GET /api/red-flags` | Auto-detected anomalies |
| `GET /api/mindmap/schemes` | Scheme aggregates for mind map |
| `GET /api/officers?state=RAJASTHAN&level=state` | Officer lookup |
| `GET /api/sources?entity=<name>&level=<union\|state\|district>` | Official links + cached news + social for any entity |
| `POST /api/refresh` | Fetch live news + Reddit for any entity on demand |
