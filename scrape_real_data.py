#!/usr/bin/env python3
"""
MGNREGA Real Data Scraper - Rajasthan (All Districts)
Scrapes actual MGNREGA data from DeshSeva.in (which syncs from data.gov.in)
Stores in fund_flow table for money-trail drill-down

Usage:
    python3 scrape_real_data.py

Run this AFTER scheme_tracker_backend.py has been started at least once
(so the database exists).
"""

import sqlite3
import requests
from bs4 import BeautifulSoup
import time
import re
import json
from datetime import datetime

from config import DB_FILE

# All Rajasthan districts from DeshSeva
RAJASTHAN_DISTRICTS = [
    'ajmer', 'alwar', 'banswara', 'baran', 'barmer',
    'bharatpur', 'bhilwara', 'bikaner', 'bundi', 'chittorgarh',
    'churu', 'dausa', 'dholpur', 'dungarpur', 'hanumangarh',
    'jaipur', 'jaisalmer', 'jalore', 'jhalawar', 'jhunjhunu',
    'jodhpur', 'karauli', 'kota', 'nagaur', 'pali',
    'pratapgarh', 'rajsamand', 'sawai-madhopur', 'sikar', 'sirohi',
    'sri-ganganagar', 'tonk', 'udaipur'
]

# ============ DATABASE SETUP ============

def setup_database():
    """Create fund_flow table and officers table for money trail"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Fund flow table - tracks money at each administrative level
    c.execute('''CREATE TABLE IF NOT EXISTS fund_flow (
        id INTEGER PRIMARY KEY,
        scheme TEXT,
        year TEXT,
        level TEXT,
        entity_name TEXT,
        parent_entity TEXT,
        state TEXT,
        district_code TEXT,

        -- Officer accountability
        officer_name TEXT,
        officer_designation TEXT,

        -- Financial data
        total_expenditure_lakh REAL,
        wages_lakh REAL,
        material_lakh REAL,
        admin_lakh REAL,

        -- Employment data
        households_worked INTEGER,
        individuals_worked INTEGER,
        person_days INTEGER,
        women_person_days INTEGER,
        sc_person_days INTEGER,
        st_person_days INTEGER,
        avg_wage_per_day REAL,
        avg_days_per_household REAL,

        -- Job card data
        active_job_cards INTEGER,
        total_workers INTEGER,

        -- Work data
        works_taken_up INTEGER,
        works_completed INTEGER,
        hh_completed_100_days INTEGER,

        -- Categories
        category_b_works_pct REAL,
        agriculture_exp_pct REAL,
        nrm_exp_pct REAL,
        payments_within_15_days_pct REAL,

        -- Metadata
        data_source TEXT,
        report_month TEXT,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

        UNIQUE(scheme, year, level, entity_name)
    )''')

    # Officers table for accountability chain
    c.execute('''CREATE TABLE IF NOT EXISTS officers (
        id INTEGER PRIMARY KEY,
        name TEXT,
        designation TEXT,
        level TEXT,
        entity TEXT,
        state TEXT,
        scheme TEXT,
        department TEXT,
        tenure_start TEXT,
        tenure_end TEXT,
        source TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(designation, entity, state)
    )''')

    conn.commit()
    conn.close()
    print("✅ Database tables created (fund_flow, officers)")


# ============ SCRAPER ============

def parse_value(text):
    """Parse numeric value from text, handling commas and special chars"""
    if not text or text.strip() in ('NA', '-', ''):
        return None
    text = text.strip().replace(',', '')
    try:
        return float(text)
    except ValueError:
        return None

def scrape_district_for_state(state_slug, district_slug):
    """Scrape MGNREGA data for one district in any state from DeshSeva."""
    url = f"https://deshseva.in/tools/mgnrega/{state_slug}/{district_slug}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"  ❌ Failed to fetch {state_slug}/{district_slug}: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    table = soup.find('table')
    if not table:
        print(f"  ❌ No table found for {state_slug}/{district_slug}")
        return None

    data = {}
    rows = table.find_all('tr')
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True).lower()
            value = cells[1].get_text(strip=True)
            data[key] = value

    if not data:
        print(f"  ❌ No data parsed for {state_slug}/{district_slug}")
        return None

    state_name    = state_slug.upper().replace('-', ' ')
    district_name = district_slug.upper().replace('-', ' ')

    result = {
        'scheme': 'NREGA',
        'year': data.get('period (financial year)', '2025-2026'),
        'level': 'district',
        'entity_name': district_name,
        'parent_entity': state_name,
        'state': state_name,
        'district_code': str(parse_value(data.get('district code', '')) or ''),
        'report_month': data.get('month (as reported)', ''),

        'total_expenditure_lakh': parse_value(data.get('total expenditure', '')),
        'wages_lakh': parse_value(data.get('wages (crore / as per source)', '')),
        'material_lakh': parse_value(data.get('material and skilled wages', '')),
        'admin_lakh': parse_value(data.get('administrative expenditure', '')),

        'households_worked': int(parse_value(data.get('total households worked', '')) or 0),
        'individuals_worked': int(parse_value(data.get('total individuals worked', '')) or 0),
        'person_days': int(parse_value(data.get('person-days of central liability (so far)', '')) or 0),
        'women_person_days': int(parse_value(data.get('women person-days', '')) or 0),
        'sc_person_days': int(parse_value(data.get('sc person-days', '')) or 0),
        'st_person_days': int(parse_value(data.get('st person-days', '')) or 0),
        'avg_wage_per_day': parse_value(data.get('average wage rate per day per person (inr)', '')),
        'avg_days_per_household': parse_value(data.get('average days of employment per household', '')),

        'active_job_cards': int(parse_value(data.get('total active job cards', '')) or 0),
        'total_workers': int(parse_value(data.get('total workers', '')) or 0),

        'works_taken_up': int(parse_value(data.get('works taken up', '')) or 0),
        'works_completed': int(parse_value(data.get('completed works', '')) or 0),
        'hh_completed_100_days': int(parse_value(data.get('hhs completed 100 days of wage employment', '')) or 0),

        'category_b_works_pct': parse_value(data.get('category b works (%)', '')),
        'agriculture_exp_pct': parse_value(data.get('expenditure on agriculture & allied works (%)', '')),
        'nrm_exp_pct': parse_value(data.get('nrm expenditure (%)', '')),
        'payments_within_15_days_pct': parse_value(data.get('payments generated within 15 days (%)', '')),

        'data_source': 'deshseva.in (synced from data.gov.in)',
    }

    return result


def scrape_district(district_slug):
    """Backwards-compatible wrapper — scrapes Rajasthan only."""
    return scrape_district_for_state('rajasthan', district_slug)


def save_district_data(data):
    """Save one district's data to fund_flow table"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    try:
        c.execute('''INSERT OR REPLACE INTO fund_flow
            (scheme, year, level, entity_name, parent_entity, state, district_code,
             total_expenditure_lakh, wages_lakh, material_lakh, admin_lakh,
             households_worked, individuals_worked, person_days, women_person_days,
             sc_person_days, st_person_days, avg_wage_per_day, avg_days_per_household,
             active_job_cards, total_workers, works_taken_up, works_completed,
             hh_completed_100_days, category_b_works_pct, agriculture_exp_pct,
             nrm_exp_pct, payments_within_15_days_pct,
             data_source, report_month, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
            (data['scheme'], data['year'], data['level'], data['entity_name'],
             data['parent_entity'], data['state'], data['district_code'],
             data['total_expenditure_lakh'], data['wages_lakh'],
             data['material_lakh'], data['admin_lakh'],
             data['households_worked'], data['individuals_worked'],
             data['person_days'], data['women_person_days'],
             data['sc_person_days'], data['st_person_days'],
             data['avg_wage_per_day'], data['avg_days_per_household'],
             data['active_job_cards'], data['total_workers'],
             data['works_taken_up'], data['works_completed'],
             data['hh_completed_100_days'], data['category_b_works_pct'],
             data['agriculture_exp_pct'], data['nrm_exp_pct'],
             data['payments_within_15_days_pct'],
             data['data_source'], data['report_month']))

        conn.commit()
    except Exception as e:
        print(f"  ❌ DB error for {data['entity_name']}: {e}")
    finally:
        conn.close()


# ============ OFFICER DATA ============

def add_officers():
    """Add known officers in the NREGA accountability chain"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Central level - public knowledge
    officers = [
        # Central
        ('Shri Shivraj Singh Chouhan', 'Union Minister, Rural Development',
         'centre', 'INDIA', 'INDIA', 'NREGA', 'Ministry of Rural Development',
         '2024-06', None, 'india.gov.in'),

        ('Smt. Annapurna Devi', 'Minister of State, Rural Development',
         'centre', 'INDIA', 'INDIA', 'NREGA', 'Ministry of Rural Development',
         '2024-06', None, 'india.gov.in'),

        # State level - Rajasthan
        ('Shri Bhajan Lal Sharma', 'Chief Minister',
         'state', 'RAJASTHAN', 'RAJASTHAN', 'NREGA', 'Government of Rajasthan',
         '2023-12', None, 'rajasthan.gov.in'),
    ]

    for name, desig, level, entity, state, scheme, dept, start, end, source in officers:
        try:
            c.execute('''INSERT OR REPLACE INTO officers
                (name, designation, level, entity, state, scheme, department,
                 tenure_start, tenure_end, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (name, desig, level, entity, state, scheme, dept, start, end, source))
        except Exception as e:
            print(f"  ⚠️ Officer insert error: {e}")

    conn.commit()
    conn.close()
    print(f"✅ Added {len(officers)} officers to accountability chain")


# ============ STATE LEVEL AGGREGATE ============

def compute_state_aggregate():
    """Sum all district data to create state-level entry"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('''SELECT
        SUM(total_expenditure_lakh) as total_exp,
        SUM(wages_lakh) as total_wages,
        SUM(material_lakh) as total_material,
        SUM(admin_lakh) as total_admin,
        SUM(households_worked) as total_hh,
        SUM(individuals_worked) as total_indiv,
        SUM(person_days) as total_pd,
        SUM(women_person_days) as total_women_pd,
        SUM(sc_person_days) as total_sc_pd,
        SUM(st_person_days) as total_st_pd,
        AVG(avg_wage_per_day) as avg_wage,
        AVG(avg_days_per_household) as avg_days,
        SUM(active_job_cards) as total_jc,
        SUM(total_workers) as total_wk,
        SUM(works_taken_up) as total_works,
        SUM(works_completed) as total_completed,
        SUM(hh_completed_100_days) as total_100days,
        COUNT(*) as district_count
    FROM fund_flow
    WHERE scheme = 'NREGA' AND state = 'RAJASTHAN' AND level = 'district'
    ''')

    row = c.fetchone()
    if row and row['district_count'] > 0:
        c.execute('''INSERT OR REPLACE INTO fund_flow
            (scheme, year, level, entity_name, parent_entity, state,
             total_expenditure_lakh, wages_lakh, material_lakh, admin_lakh,
             households_worked, individuals_worked, person_days, women_person_days,
             sc_person_days, st_person_days, avg_wage_per_day, avg_days_per_household,
             active_job_cards, total_workers, works_taken_up, works_completed,
             hh_completed_100_days, data_source, scraped_at)
            VALUES ('NREGA', '2025-2026', 'state', 'RAJASTHAN', 'INDIA', 'RAJASTHAN',
                    ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    'Aggregated from district data', CURRENT_TIMESTAMP)''',
            (row['total_exp'], row['total_wages'], row['total_material'], row['total_admin'],
             row['total_hh'], row['total_indiv'], row['total_pd'], row['total_women_pd'],
             row['total_sc_pd'], row['total_st_pd'], row['avg_wage'], row['avg_days'],
             row['total_jc'], row['total_wk'], row['total_works'], row['total_completed'],
             row['total_100days']))
        conn.commit()
        print(f"✅ State aggregate: {row['district_count']} districts → 1 state row")

    conn.close()


# ============ MAIN ============

def main():
    print("=" * 65)
    print("  MGNREGA REAL DATA SCRAPER — RAJASTHAN")
    print("  Source: DeshSeva.in (synced from data.gov.in)")
    print("=" * 65)
    print()

    # Step 1: Setup
    print("Step 1: Setting up database tables...")
    setup_database()
    print()

    # Step 2: Scrape all districts
    print(f"Step 2: Scraping {len(RAJASTHAN_DISTRICTS)} districts...")
    print("-" * 50)

    success = 0
    failed = 0

    for i, district in enumerate(RAJASTHAN_DISTRICTS, 1):
        print(f"  [{i:2d}/{len(RAJASTHAN_DISTRICTS)}] {district.upper().replace('-',' ')}...", end=" ")

        data = scrape_district(district)
        if data:
            save_district_data(data)
            exp = data['total_expenditure_lakh']
            exp_str = f"₹{exp:.0f}L" if exp else "N/A"
            hh = data['households_worked']
            print(f"✅ Exp: {exp_str} | HH: {hh:,} | PD: {data['person_days']:,}")
            success += 1
        else:
            failed += 1

        # Be polite to the server
        time.sleep(1)

    print("-" * 50)
    print(f"  ✅ Success: {success} | ❌ Failed: {failed}")
    print()

    # Step 3: Compute state aggregate
    print("Step 3: Computing state-level aggregate...")
    compute_state_aggregate()
    print()

    # Step 4: Add officers
    print("Step 4: Adding officer accountability data...")
    add_officers()
    print()

    # Step 5: Summary
    print("=" * 65)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    c.execute('SELECT COUNT(*) FROM fund_flow')
    total = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM officers')
    officers = c.fetchone()[0]

    c.execute('''SELECT entity_name, total_expenditure_lakh, households_worked,
                        works_taken_up, works_completed, avg_wage_per_day
                 FROM fund_flow
                 WHERE level = 'district' AND scheme = 'NREGA'
                 ORDER BY total_expenditure_lakh DESC
                 LIMIT 5''')
    top = c.fetchall()

    c.execute('''SELECT entity_name, works_taken_up, works_completed,
                        ROUND(100.0 * works_completed / works_taken_up, 1) as completion_pct
                 FROM fund_flow
                 WHERE level = 'district' AND scheme = 'NREGA' AND works_taken_up > 0
                 ORDER BY completion_pct ASC
                 LIMIT 5''')
    worst_completion = c.fetchall()

    conn.close()

    print(f"  📊 Total fund_flow records: {total}")
    print(f"  👤 Officers tracked: {officers}")
    print()
    print("  TOP 5 DISTRICTS BY EXPENDITURE:")
    print("  " + "-" * 55)
    for name, exp, hh, wu, wc, wage in top:
        print(f"  {name:<20s} ₹{exp:>10,.0f}L  HH:{hh:>8,}  Wage:₹{wage:.0f}/day")

    print()
    print("  🚨 WORST WORK COMPLETION RATES:")
    print("  " + "-" * 55)
    for name, wu, wc, pct in worst_completion:
        print(f"  {name:<20s} {wc:>6,} / {wu:>6,} works completed ({pct}%)")

    print()
    print("=" * 65)
    print("✅ DONE! Real MGNREGA data loaded.")
    print()
    print("Next steps:")
    print("  1. Restart backend:  python3 scheme_tracker_backend.py")
    print("  2. Open dashboard:   http://localhost:3000/dashboard.html")
    print("  3. Or query API:     curl http://localhost:5000/api/money-trail/RAJASTHAN")
    print("=" * 65)


if __name__ == '__main__':
    main()
