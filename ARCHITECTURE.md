# System Architecture & Design

## 🏗️ Complete System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                          YOUR HOME SERVER                           │
│                    (16GB RAM, 400GB Disk, Linux)                   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                 BACKEND (Python Flask)                      │ │
│  │                                                              │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  Web Crawlers (BeautifulSoup)                        │  │ │
│  │  │  ├─ pmjay.gov.in (Health)                           │  │ │
│  │  │  ├─ nrega.nic.in (Employment)                       │  │ │
│  │  │  ├─ pmaymis.gov.in (Housing)                        │  │ │
│  │  │  ├─ pmkisan.gov.in (Agriculture)                    │  │ │
│  │  │  ├─ jaljeevan.gov.in (Water)                        │  │ │
│  │  │  └─ pmujjwala.gov.in (Gas)                          │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                           ↓ (Every 6 hours)                │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  Data Parser & Normalizer                            │  │ │
│  │  │  ├─ Extract state names                             │  │ │
│  │  │  ├─ Convert units (Cr, lakhs, etc.)                 │  │ │
│  │  │  ├─ Match fiscal years                              │  │ │
│  │  │  └─ Standardize scheme names                        │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                           ↓                                 │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  Anomaly Detector                                    │  │ │
│  │  │  ├─ Fund allocated ≠ Spent                          │  │ │
│  │  │  ├─ Low utilization (<50%)                          │  │ │
│  │  │  ├─ Cost per beneficiary outliers                   │  │ │
│  │  │  └─ Year-on-year changes                            │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                           ↓                                 │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  SQLite Database (scheme_tracker.db)                 │  │ │
│  │  │                                                       │  │ │
│  │  │  schemes table                                       │  │ │
│  │  │  ├─ id, name, ministry, description                │  │ │
│  │  │  └─ Total: 50+ schemes                             │  │ │
│  │  │                                                       │  │ │
│  │  │  financials table                                    │  │ │
│  │  │  ├─ scheme_id, state, year                         │  │ │
│  │  │  ├─ allocated_cr, released_cr, spent_cr            │  │ │
│  │  │  ├─ beneficiaries, data_source                     │  │ │
│  │  │  └─ Total: 68-5000+ records                        │  │ │
│  │  │                                                       │  │ │
│  │  │  officers table (for accountability)                │  │ │
│  │  │  ├─ name, designation, state, scheme               │  │ │
│  │  │  └─ tenure_start, tenure_end                       │  │ │
│  │  │                                                       │  │ │
│  │  │  discrepancies table (auto-detected)                │  │ │
│  │  │  ├─ scheme_id, state, year                         │  │ │
│  │  │  ├─ discrepancy_type, severity                     │  │ │
│  │  │  └─ gap_cr (fund missing)                          │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  │                           ↓                                 │ │
│  │  ┌──────────────────────────────────────────────────────┐  │ │
│  │  │  REST API Server (Port 5000)                        │  │ │
│  │  │                                                       │  │ │
│  │  │  GET  /api/health                                   │  │ │
│  │  │  GET  /api/schemes                                  │  │ │
│  │  │  GET  /api/dashboard                                │  │ │
│  │  │  GET  /api/utilization?year=2024                    │  │ │
│  │  │  GET  /api/discrepancies                            │  │ │
│  │  │  GET  /api/state/:name                              │  │ │
│  │  │  POST /api/add-financial-data                       │  │ │
│  │  │  GET  /api/last-crawl                               │  │ │
│  │  └──────────────────────────────────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │           FRONTEND (React Dashboard, Port 3000)              │ │
│  │                                                              │ │
│  │  ┌────────────────────────────────────────────────────────┐ │ │
│  │  │  Tabs                                                 │ │ │
│  │  │  ├─ Overview (KPI cards, low utilization states)      │ │ │
│  │  │  ├─ Fund Utilization (table, allocated vs spent)      │ │ │
│  │  │  ├─ Red Flags (detected discrepancies)               │ │ │
│  │  │  └─ State-wise (select state → all schemes)          │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  │                                                              │ │
│  │  ┌────────────────────────────────────────────────────────┐ │ │
│  │  │  Components                                           │ │ │
│  │  │  ├─ KPI Cards (total schemes, beneficiaries, gaps)    │ │ │
│  │  │  ├─ Utilization Bars (% spent with color coding)     │ │ │
│  │  │  ├─ Data Tables (sortable, filterable)              │ │ │
│  │  │  ├─ Discrepancy Cards (severity indicators)          │ │ │
│  │  │  └─ State Selector (28 states with map-like grid)    │ │ │
│  │  └────────────────────────────────────────────────────────┘ │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
              ┌───────────────────────────────────┐
              │     External Access (Optional)    │
              │                                   │
              │  Local Network:                  │
              │  http://192.168.1.x:3000         │
              │                                   │
              │  Public Internet (Cloudflare):  │
              │  https://schemes.yourdomain.com │
              └───────────────────────────────────┘
```

---

## 🔄 Data Flow Diagram

```
GOVERNMENT WEBSITES
   ↓
   ├─ pmjay.gov.in (HTML)
   ├─ nrega.nic.in (HTML)
   ├─ pmaymis.gov.in (HTML)
   └─ ... (other portals)
   ↓
WEB SCRAPER
   │
   ├─ Parse HTML using BeautifulSoup
   ├─ Extract tables & data
   ├─ Handle pagination
   └─ Retry on failures
   ↓
DATA NORMALIZER
   │
   ├─ Standardize state names
   │  (e.g., "UP" → "Uttar Pradesh")
   │
   ├─ Convert units
   │  (e.g., "500 Crores" → 500)
   │
   ├─ Match fiscal years
   │  (e.g., "2023-24" → 2024)
   │
   └─ Link scheme IDs
      (e.g., "PMJAY" → id: 1)
   ↓
ANOMALY DETECTOR
   │
   ├─ Flag: allocated > 0, spent = 0
   │         → Fund allocated but not used
   │
   ├─ Flag: spent/allocated < 50%
   │         → Low utilization
   │
   ├─ Flag: year-to-year jump
   │         → Unexpected budget change
   │
   └─ Flag: cost outliers
       → Beneficiary count mismatch
   ↓
DATABASE INSERT
   │
   ├─ financials table
   │  (scheme, state, year, allocated, spent, beneficiaries)
   │
   ├─ discrepancies table
   │  (auto-populated from anomalies)
   │
   └─ Timestamp for tracking
   ↓
API ENDPOINTS
   │
   ├─ /api/dashboard → Summary stats
   ├─ /api/utilization → All fund data
   ├─ /api/discrepancies → Flagged issues
   ├─ /api/state/:name → State details
   └─ /api/schemes → Scheme list
   ↓
REACT FRONTEND
   │
   ├─ Fetch from API
   ├─ Process data
   ├─ Render components
   ├─ Apply color coding
   │  (Green: >80% util, Yellow: 50-80%, Red: <50%)
   │
   └─ Display to user
   ↓
USER SEES:
   "PM-JAY in Uttar Pradesh spent only ₹380 Cr of ₹920 Cr allocated"
   "Fund gap: ₹540 Cr (64% unspent) 🚨"
```

---

## 📊 Database Schema

```sql
-- SCHEMES TABLE
CREATE TABLE schemes (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE,                          -- "PM-JAY", "NREGA", etc.
    ministry TEXT,                             -- "Ministry of Health"
    description TEXT,
    website TEXT,                              -- Government portal URL
    created_at TIMESTAMP
);

-- FINANCIALS TABLE (Core Data)
CREATE TABLE financials (
    id INTEGER PRIMARY KEY,
    scheme_id INTEGER FOREIGN KEY,
    state TEXT,                                -- "Maharashtra", "UP", etc.
    year INTEGER,                              -- 2024, 2023, etc.
    allocated_cr REAL,                         -- Budget allocated (₹ Crores)
    released_cr REAL,                          -- Budget released (₹ Crores)
    spent_cr REAL,                             -- Budget actually spent (₹ Crores)
    beneficiaries INTEGER,                     -- Number of people benefited
    data_source TEXT,                          -- "pmjay.gov.in"
    scraped_at TIMESTAMP,                      -- When this data was crawled
    UNIQUE(scheme_id, state, year)             -- No duplicates
);

-- OFFICERS TABLE (Accountability)
CREATE TABLE officers (
    id INTEGER PRIMARY KEY,
    name TEXT,                                 -- "Ms. Priya Kumar"
    designation TEXT,                          -- "IAS", "District Magistrate"
    state TEXT,
    scheme_id INTEGER FOREIGN KEY,
    ministry TEXT,
    tenure_start TEXT,                         -- "2022-01"
    tenure_end TEXT,                           -- NULL if current
    added_at TIMESTAMP
);

-- DISCREPANCIES TABLE (Auto-detected)
CREATE TABLE discrepancies (
    id INTEGER PRIMARY KEY,
    scheme_id INTEGER FOREIGN KEY,
    state TEXT,
    year INTEGER,
    discrepancy_type TEXT,                     -- "low_utilization", "zero_spend"
    description TEXT,                          -- "Allocated but not spent"
    severity TEXT,                             -- "critical", "high", "medium"
    gap_cr REAL,                               -- Rupees in Crores
    detected_at TIMESTAMP
);

-- DATA SOURCES TABLE (Tracking)
CREATE TABLE data_sources (
    id INTEGER PRIMARY KEY,
    scheme_id INTEGER FOREIGN KEY,
    source_url TEXT,
    source_name TEXT,                          -- "PM-JAY Official Dashboard"
    last_scraped TIMESTAMP,
    data_type TEXT                             -- "dashboard", "budget", "report"
);
```

---

## 🔄 Crawler Lifecycle

```
┌──────────────────────────────────────────────┐
│  Every 6 Hours (or on demand)               │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  1. FETCH                                    │
│     ├─ GET pmjay.gov.in/statewise-report    │
│     ├─ GET nrega.nic.in/dashboard           │
│     └─ ... other sources                     │
│     ⏱️  ~30 seconds for all                  │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  2. PARSE                                    │
│     ├─ BeautifulSoup HTML parsing           │
│     ├─ Extract <table> elements             │
│     ├─ Find state names, numbers            │
│     └─ Handle variations in format          │
│     ⏱️  ~10 seconds                          │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  3. NORMALIZE                                │
│     ├─ State: "MAHARASHTRA" → "Maharashtra" │
│     ├─ Number: "500,00,000" → 50000000      │
│     ├─ Amount: "500 Cr" → 500               │
│     └─ Year: "2023-24" → 2024               │
│     ⏱️  ~5 seconds                           │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  4. ANALYZE                                  │
│     ├─ Calculate utilization %              │
│     ├─ Find fund gaps                       │
│     ├─ Detect anomalies                     │
│     └─ Flag for review                      │
│     ⏱️  ~5 seconds                           │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  5. STORE                                    │
│     ├─ INSERT into financials table         │
│     ├─ INSERT into discrepancies table      │
│     ├─ UPDATE last_crawl timestamp          │
│     └─ Commit transaction                   │
│     ⏱️  ~10 seconds                          │
└──────────────────────────────────────────────┘
          ↓
┌──────────────────────────────────────────────┐
│  6. NOTIFY (Optional)                        │
│     ├─ Check for critical issues            │
│     ├─ Send email alert (if configured)     │
│     └─ Log summary                          │
│     ⏱️  ~5 seconds                           │
└──────────────────────────────────────────────┘
          ↓
✅ Complete (~1 minute for entire cycle)
   Wait 6 hours...
          ↓
🔄 Repeat
```

---

## 🎨 Frontend Component Tree

```
<App>
  │
  ├─ Header
  │  └─ Title, subtitle, last crawl timestamp
  │
  ├─ Navigation
  │  ├─ Overview tab
  │  ├─ Fund Utilization tab
  │  ├─ Red Flags tab
  │  └─ State-wise tab
  │
  ├─ Content (Dynamic)
  │  │
  │  ├─ OVERVIEW
  │  │  ├─ KPICard (Active Schemes)
  │  │  ├─ KPICard (Data Points)
  │  │  ├─ KPICard (Beneficiaries)
  │  │  ├─ KPICard (Fund Gaps)
  │  │  └─ LowUtilizationTable
  │  │
  │  ├─ FUND UTILIZATION
  │  │  └─ AllSchemeTable
  │  │     └─ UtilizationBar (each row)
  │  │
  │  ├─ RED FLAGS
  │  │  └─ DiscrepancyCard[] (list)
  │  │     ├─ Scheme name
  │  │     ├─ Fund gap amount
  │  │     └─ Severity badge
  │  │
  │  └─ STATE-WISE
  │     ├─ StateSelector (grid of state buttons)
  │     └─ StateTable (if state selected)
  │
  └─ Footer
     └─ Data source info, privacy notice
```

---

## 📈 Performance Characteristics

### Memory Usage
```
Component          Typical Usage
─────────────────────────────────
Python Flask       ~50 MB
Node.js            ~100 MB
SQLite (in memory) ~50 MB
Scrapers (running) ~100 MB
─────────────────────────────────
Total              ~300 MB (your machine: 16GB ✓)
```

### Disk Usage
```
Item                    Size
─────────────────────────────────
scheme_tracker.db       ~5 MB (68 records)
scheme_tracker.db       ~20 MB (1000 records)
scheme_tracker.db       ~100 MB (10000 records)
─────────────────────────────────
5 years all schemes     ~1 GB (your machine: 400GB ✓)
```

### Network Usage
```
Per Crawl Cycle
  Fetch govn websites:  ~50 MB
  Parse HTML:           ~0 MB
  Database update:      ~0.1 MB
─────────────────────────
  Total per 6 hours:    ~50 MB
  Per month:            ~100 MB
  Per year:             ~1.2 GB
```

### CPU Usage
```
Idle:             <1% CPU
Crawling:         ~10% CPU (for ~1 minute)
Dashboard views:  <5% CPU
```

---

## 🔐 Security Architecture

```
┌─────────────────────────────────────────┐
│  EXTERNAL INTERNET                      │
│  (Untrusted)                           │
└──────────────────┬──────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
         ↓                   ↓
    Government         Your Home Server
    Websites           (SECURE)
    (Read-only)        
                       ┌──────────────┐
                       │ FIREWALL     │
                       │ (Optional)   │
                       └──────┬───────┘
                              │
                    ┌─────────┴──────────┐
                    │                    │
                    ↓                    ↓
              Port 5000            Port 3000
              (Backend API)        (Frontend)
              
Key Security Points:
✅ All data is public (scraped from govt)
✅ No user credentials stored
✅ No personal data collected
✅ Self-hosted (complete control)
✅ No cloud dependencies
✅ Can run offline after initial crawl
⚠️  Open ports on local network only (unless using Cloudflare)
⚠️  Don't expose to public internet without HTTPS/auth
```

---

## 🔧 API Contract

### Request/Response Example

**Request**: GET /api/utilization?year=2024

**Response**:
```json
{
  "year": 2024,
  "data": [
    {
      "scheme": "PM-JAY",
      "state": "Maharashtra",
      "allocated_cr": 500,
      "spent_cr": 450,
      "beneficiaries": 2000000,
      "utilization_pct": 90.0,
      "fund_gap": 50.0
    },
    {
      "scheme": "PM-JAY",
      "state": "Bihar",
      "allocated_cr": 300,
      "spent_cr": 45,
      "beneficiaries": 250000,
      "utilization_pct": 15.0,
      "fund_gap": 255.0
    }
    // ... more
  ],
  "total_records": 68
}
```

---

## 🚀 Deployment Topologies

### Single Machine (Your Setup)
```
┌─────────────────────┐
│  Your Home Server   │
│  ├─ Backend:5000   │
│  ├─ Frontend:3000  │
│  └─ DB: SQLite     │
└─────────────────────┘
  Access: localhost:3000
```

### Multi-Device (Same WiFi)
```
┌─────────────────────────────────────┐
│  Your Home WiFi Network             │
├─────────────────────────────────────┤
│  Server Machine (16GB RAM)          │
│  ├─ Backend:5000                   │
│  ├─ Frontend:3000                  │
│  └─ DB: SQLite                     │
│                                    │
│  Client Machine 1, 2, 3...         │
│  └─ Browser → Server IP:3000       │
└─────────────────────────────────────┘
  Access: 192.168.1.x:3000
```

### Global Access (Cloudflare)
```
┌────────────────────────────────────────┐
│  Your Home Server                      │
│  └─ Cloudflare Tunnel Active          │
└─────────────┬──────────────────────────┘
              │
              ↓ (HTTPS Encrypted)
┌────────────────────────────────────────┐
│  Cloudflare Network (CDN)              │
└─────────────┬──────────────────────────┘
              │
              ↓
┌────────────────────────────────────────┐
│  Anyone on Internet                    │
│  Browser → schemes.yourdomain.com     │
│  (Secure HTTPS)                        │
└────────────────────────────────────────┘
```

---

## 📝 Data Integrity

```
Source Website       Scraper        Parser         Database
     │                  │              │               │
     │──→ HTML ────→ Parser ──→ Extracted Data ──→ Insert
     │    (noisy)     (robust)  (normalized)    (validated)
     │
     │ Handles:
     │ - Partial HTML
     │ - Missing values
     │ - Format changes
     │ - Duplicate entries
```

**Validation Checks**:
- ✅ Allocated ≥ Released ≥ Spent (logical order)
- ✅ Beneficiaries > 0 for valid entries
- ✅ Year is valid (2020-2024)
- ✅ State name matches known states
- ✅ Scheme name matches registered schemes

---

## 🔄 Sync Strategy

```
First Run:
  Load sample data (68 records) ──→ Database
  
Ongoing:
  Every 6 hours:
    Latest data from govn ──→ Parse ──→ Merge
    
  Update Logic:
    IF (scheme_id, state, year) EXISTS
      THEN UPDATE spent_cr, beneficiaries
      ELSE INSERT new row

Result:
  - Always up-to-date
  - No data loss
  - Historical tracking (year-to-year changes)
```

---

**This architecture is:**
- ✅ Simple (no complex dependencies)
- ✅ Reliable (handles network issues)
- ✅ Scalable (easily add more schemes)
- ✅ Transparent (see all data)
- ✅ Autonomous (runs without you!)

---

**Next**: See QUICK_START.md to get it running! 🚀
