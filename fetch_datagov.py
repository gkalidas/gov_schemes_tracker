#!/usr/bin/env python3
"""
data.gov.in official data fetcher + cross-verifier.

Two jobs:
  1. datagov_fetch  — pull official NREGA district data from data.gov.in and
                      store it in datagov_nrega table (authoritative source).
  2. datagov_verify — compare datagov_nrega against fund_flow (our DeshSeva
                      scrape) and write discrepancies > VERIFY_TOLERANCE_PCT
                      into the discrepancies table.

Requires DATA_GOV_API_KEY in config.py or the DATA_GOV_API_KEY env var.
Register free at https://data.gov.in/user/register

If the key is missing, both functions log a warning and return — the rest of
the app is unaffected.
"""

import json
import logging
import re
import sqlite3
import time

import requests

import config
import constants

logger = logging.getLogger(__name__)

# ── known resource search terms ───────────────────────────────────────────────

# We search data.gov.in for datasets whose titles contain these keywords, then
# pick the best match. If the platform renames a dataset, updating these is
# the only change needed.
_NREGA_SEARCH_TERMS = ['district-wise mgnrega data at a glance', 'district mgnrega glance']

# Cache table — stores discovered resource IDs so we don't search on every run.
_CACHE_TABLE = 'datagov_resource_cache'

# Official data table — stores rows pulled from data.gov.in.
_DATA_TABLE  = 'datagov_nrega'

# ── field name heuristics ─────────────────────────────────────────────────────
# data.gov.in column names change between dataset versions.
# Each entry maps our internal key → list of substrings to match (case-insensitive).
_FIELD_MAP = {
    'state':              ['state', 'uts', 'state/ut'],
    'district':           ['district'],
    'fin_year':           ['year', 'financial year', 'fin year'],
    'expenditure_lakh':   ['expenditure', 'total expend', 'expend'],
    'person_days':        ['person-days', 'person days', 'persondays'],
    'households_worked':  ['household', 'hh worked', 'hhld'],
    'avg_wage':           ['wage rate', 'avg wage', 'average wage'],
    'works_taken_up':     ['works taken', 'work taken'],
    'works_completed':    ['completed work', 'works completed'],
    'active_job_cards':   ['job card', 'active job'],
}


def _match_field(col_name: str) -> str | None:
    """Return our internal key for a data.gov.in column name, or None."""
    col_lower = col_name.lower()
    for our_key, patterns in _FIELD_MAP.items():
        for p in patterns:
            if p in col_lower:
                return our_key
    return None


# ── db helpers ────────────────────────────────────────────────────────────────

def init_tables():
    conn = sqlite3.connect(config.DB_FILE)
    c    = conn.cursor()
    c.execute(f'''CREATE TABLE IF NOT EXISTS {_CACHE_TABLE} (
        search_term  TEXT PRIMARY KEY,
        resource_id  TEXT NOT NULL,
        title        TEXT,
        discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute(f'''CREATE TABLE IF NOT EXISTS {_DATA_TABLE} (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        state           TEXT,
        district        TEXT,
        fin_year        TEXT,
        expenditure_lakh REAL,
        person_days     INTEGER,
        households_worked INTEGER,
        avg_wage        REAL,
        works_taken_up  INTEGER,
        works_completed INTEGER,
        active_job_cards INTEGER,
        raw_json        TEXT,
        fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(state, district, fin_year)
    )''')
    conn.commit()
    conn.close()


def _save_resource_id(search_term, resource_id, title):
    conn = sqlite3.connect(config.DB_FILE)
    conn.execute(
        f'INSERT OR REPLACE INTO {_CACHE_TABLE} (search_term, resource_id, title) VALUES (?,?,?)',
        (search_term, resource_id, title)
    )
    conn.commit()
    conn.close()


def _cached_resource_id(search_term):
    conn = sqlite3.connect(config.DB_FILE)
    row  = conn.execute(
        f'SELECT resource_id FROM {_CACHE_TABLE} WHERE search_term=?', (search_term,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


# ── data.gov.in API helpers ───────────────────────────────────────────────────

_BASE = 'https://api.data.gov.in'

def _api(path, params=None):
    """GET request to data.gov.in API. Returns parsed JSON or raises."""
    p = {'api-key': config.DATA_GOV_API_KEY, 'format': 'json'}
    if params:
        p.update(params)
    resp = requests.get(f'{_BASE}{path}', params=p, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _discover_resource_id(search_term):
    """Search data.gov.in for a dataset by title keyword. Returns resource_id."""
    cached = _cached_resource_id(search_term)
    if cached:
        return cached

    logger.info('[datagov] Discovering resource for: %s', search_term)
    try:
        data = _api('/lists', {
            'filters[keyword]': 'mgnrega',
            'filters[title]': search_term.split()[0],
            'limit': 20,
        })
    except Exception as e:
        logger.warning('[datagov] Search failed: %s', e)
        return None

    records = data.get('records', [])
    # Pick the record whose title best matches our search term
    best_id, best_title = None, None
    for rec in records:
        title = (rec.get('title') or '').lower()
        if all(w in title for w in search_term.split()):
            best_id    = rec.get('index_name') or rec.get('resource_id')
            best_title = rec.get('title', '')
            break

    if best_id:
        _save_resource_id(search_term, best_id, best_title)
        logger.info('[datagov] Found resource: %s — %s', best_id, best_title)

    return best_id


def _fetch_all_records(resource_id):
    """Paginate through a data.gov.in resource and return all rows."""
    limit  = 100
    offset = 0
    all_records = []

    while True:
        try:
            data = _api(f'/resource/{resource_id}', {'limit': limit, 'offset': offset})
        except Exception as e:
            logger.warning('[datagov] Fetch error at offset %d: %s', offset, e)
            break

        records = data.get('records', [])
        if not records:
            break
        all_records.extend(records)

        total = int(data.get('total', 0))
        offset += limit
        if offset >= total:
            break
        time.sleep(config.DOMAIN_DELAYS.get('api.data.gov.in', 3))

    return all_records


def _map_record(raw: dict) -> dict:
    """Map a raw data.gov.in row to our internal schema."""
    mapped = {'raw_json': json.dumps(raw, ensure_ascii=False)}
    for col, val in raw.items():
        key = _match_field(col)
        if key:
            mapped[key] = val
    return mapped


def _coerce(val, typ):
    if val is None or val == '' or str(val).strip() in ('-', 'NA', 'N/A'):
        return None
    try:
        s = str(val).replace(',', '').strip()
        return typ(s)
    except (ValueError, TypeError):
        return None


# ── public: fetch ─────────────────────────────────────────────────────────────

def fetch():
    """
    Pull official NREGA district data from data.gov.in and store in datagov_nrega.
    Skips gracefully if DATA_GOV_API_KEY is not set.
    """
    if not config.DATA_GOV_API_KEY:
        logger.warning('[datagov] DATA_GOV_API_KEY not set — skipping fetch. '
                       'Register at https://data.gov.in/user/register')
        return 0

    init_tables()

    resource_id = None
    for term in _NREGA_SEARCH_TERMS:
        resource_id = _discover_resource_id(term)
        if resource_id:
            break

    if not resource_id:
        logger.warning('[datagov] Could not discover NREGA district resource ID.')
        return 0

    logger.info('[datagov] Fetching all records from resource %s', resource_id)
    records = _fetch_all_records(resource_id)
    if not records:
        logger.warning('[datagov] No records returned.')
        return 0

    conn = sqlite3.connect(config.DB_FILE)
    c    = conn.cursor()
    saved = 0

    for raw in records:
        m = _map_record(raw)
        state    = str(m.get('state', '') or '').upper().strip()
        district = str(m.get('district', '') or '').upper().strip()
        fin_year = str(m.get('fin_year', '') or '').strip()

        if not state or not district:
            continue

        c.execute(f'''INSERT OR REPLACE INTO {_DATA_TABLE}
            (state, district, fin_year, expenditure_lakh, person_days,
             households_worked, avg_wage, works_taken_up, works_completed,
             active_job_cards, raw_json, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
            (state, district, fin_year,
             _coerce(m.get('expenditure_lakh'), float),
             _coerce(m.get('person_days'),      int),
             _coerce(m.get('households_worked'), int),
             _coerce(m.get('avg_wage'),          float),
             _coerce(m.get('works_taken_up'),    int),
             _coerce(m.get('works_completed'),   int),
             _coerce(m.get('active_job_cards'),  int),
             m['raw_json'])
        )
        saved += 1

    conn.commit()
    conn.close()
    logger.info('[datagov] Saved %d district records.', saved)
    return saved


# ── public: verify ────────────────────────────────────────────────────────────

def verify():
    """
    Compare datagov_nrega (official) against fund_flow (DeshSeva scrape).
    Writes discrepancies beyond VERIFY_TOLERANCE_PCT into the discrepancies table.
    Returns the number of discrepancies found.
    """
    init_tables()

    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    c    = conn.cursor()

    # Fields to compare: (datagov column, fund_flow column, label)
    compare_fields = [
        ('expenditure_lakh',  'total_expenditure_lakh', 'Total Expenditure (lakh)'),
        ('person_days',       'person_days',            'Person-days'),
        ('households_worked', 'households_worked',      'Households Worked'),
        ('avg_wage',          'avg_wage_per_day',       'Avg Wage/Day'),
        ('works_taken_up',    'works_taken_up',         'Works Taken Up'),
        ('works_completed',   'works_completed',        'Works Completed'),
    ]

    c.execute(f'SELECT * FROM {_DATA_TABLE}')
    official_rows = c.fetchall()

    found     = 0
    year_2425 = '2024-25'

    # Get NREGA scheme ID
    c.execute("SELECT id FROM schemes WHERE name=?", (constants.SCHEME_NREGA,))
    scheme_row = c.fetchone()
    scheme_id  = scheme_row['id'] if scheme_row else None

    for off in official_rows:
        state    = off['state']
        district = off['district']

        # Match against fund_flow — district names may have small differences
        c.execute(
            "SELECT * FROM fund_flow WHERE scheme=? AND level='district' "
            "AND state=? AND entity_name=?",
            (constants.SCHEME_NREGA, state, district)
        )
        our_row = c.fetchone()
        if not our_row:
            # Try normalising: strip spaces, replace hyphens
            norm = re.sub(r'[-\s]+', ' ', district).strip()
            c.execute(
                "SELECT * FROM fund_flow WHERE scheme=? AND level='district' "
                "AND state=? AND REPLACE(REPLACE(entity_name,'-',' '),'  ',' ')=?",
                (constants.SCHEME_NREGA, state, norm)
            )
            our_row = c.fetchone()

        if not our_row:
            continue  # district not yet scraped by us — skip

        tol = config.VERIFY_TOLERANCE_PCT / 100.0

        for dg_col, ff_col, label in compare_fields:
            dg_val = off[dg_col]
            ff_val = our_row[ff_col]

            if dg_val is None or ff_val is None:
                continue
            if dg_val == 0 and ff_val == 0:
                continue

            base  = max(abs(dg_val), abs(ff_val), 1)
            diff  = abs(dg_val - ff_val)
            pct   = diff / base

            if pct > tol:
                desc = (
                    f'{label}: official={dg_val:,.1f}  ours={ff_val:,.1f}  '
                    f'diff={pct*100:.1f}%'
                )
                severity = 'high' if pct > 0.20 else 'medium'
                gap      = round(dg_val - ff_val, 2) if 'lakh' in dg_col else None

                c.execute(
                    '''INSERT OR IGNORE INTO discrepancies
                       (scheme_id, state, year, discrepancy_type, description, severity, gap_cr)
                       VALUES (?,?,?,?,?,?,?)''',
                    (scheme_id, f'{state} / {district}', year_2425,
                     f'data_mismatch:{dg_col}', desc, severity, gap)
                )
                found += 1
                logger.info('[verify] %s / %s — %s', state, district, desc)

    conn.commit()
    conn.close()
    logger.info('[datagov] Verification complete. %d discrepancies flagged.', found)
    return found


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import argparse
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description='data.gov.in fetcher + cross-verifier')
    parser.add_argument('--fetch',  action='store_true', help='Pull official NREGA data')
    parser.add_argument('--verify', action='store_true', help='Cross-verify against our data')
    args = parser.parse_args()

    if not args.fetch and not args.verify:
        parser.print_help()
    if args.fetch:
        n = fetch()
        print(f'Fetched {n} records.')
    if args.verify:
        n = verify()
        print(f'{n} discrepancies flagged.')
