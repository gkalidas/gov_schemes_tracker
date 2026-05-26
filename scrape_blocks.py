"""
Scrape block-level NREGA data for all 33 Rajasthan districts using Playwright.

nrega.nic.in is an ASP.NET ViewState app — needs a real browser.
The citizen dashboard URL pattern is:
  https://nreganarep.nic.in/netnrega/homestciti.aspx?state_code=27&district_code=XXXX

Each district page has a table with one row per block showing:
  households, person-days, expenditure, works, wage data etc.

Run: python3 scrape_blocks.py
     python3 scrape_blocks.py --district UDAIPUR   (single district)
"""

import sqlite3
import time
import sys
import argparse
from playwright.sync_api import sync_playwright

from config import DB_FILE

# District code map — matches fund_flow.entity_name to nrega district code
DISTRICT_CODES = {
    'AJMER': '2701', 'ALWAR': '2702', 'BANSWARA': '2703', 'BARAN': '2704',
    'BARMER': '2705', 'BHARATPUR': '2706', 'BHILWARA': '2707', 'BIKANER': '2708',
    'BUNDI': '2709', 'CHITTORGARH': '2710', 'CHURU': '2711', 'DAUSA': '2712',
    'DHOLPUR': '2713', 'DUNGARPUR': '2714', 'HANUMANGARH': '2715', 'JAIPUR': '2716',
    'JAISALMER': '2717', 'JALORE': '2718', 'JHALAWAR': '2719', 'JHUNJHUNU': '2720',
    'JODHPUR': '2721', 'KARAULI': '2722', 'KOTA': '2723', 'NAGAUR': '2724',
    'PALI': '2725', 'PRATAPGARH': '2736', 'RAJSAMAND': '2726',
    'SAWAI MADHOPUR': '2727', 'SIKAR': '2728', 'SIROHI': '2729',
    'SRI GANGANAGAR': '2730', 'TONK': '2731', 'UDAIPUR': '2732',
}

NOTIFIED_WAGE = 266


def parse_int(text):
    if not text:
        return None
    text = text.strip().replace(',', '').replace(' ', '')
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def parse_float(text):
    if not text:
        return None
    text = text.strip().replace(',', '').replace(' ', '')
    try:
        return float(text)
    except (ValueError, TypeError):
        return None


def scrape_district_blocks(page, district_name, district_code):
    url = (f'https://nreganarep.nic.in/netnrega/homestciti.aspx'
           f'?state_code=27&state_name=RAJASTHAN'
           f'&district_code={district_code}&district_name={district_name}')

    print(f'  Fetching {district_name} ({district_code})...', flush=True)
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state('networkidle', timeout=20000)
    except Exception as e:
        print(f'  ❌ Load failed: {e}', flush=True)
        return []

    # Find the block data table — look for table with numeric data rows
    tables = page.query_selector_all('table')
    block_table = None
    for t in tables:
        headers = [th.inner_text().strip() for th in t.query_selector_all('th')]
        header_text = ' '.join(headers).lower()
        if any(w in header_text for w in ['block', 'household', 'expenditure', 'person']):
            block_table = t
            break

    if not block_table:
        # Try finding by content — look for table with many rows of numbers
        for t in tables:
            rows = t.query_selector_all('tr')
            if len(rows) > 5:
                first_cells = [td.inner_text().strip() for td in rows[1].query_selector_all('td')]
                if first_cells and any(c.replace(',', '').isdigit() for c in first_cells):
                    block_table = t
                    break

    if not block_table:
        print(f'  ⚠️  No block table found for {district_name}', flush=True)
        # Debug: print page text snippet
        print(f'  Page snippet: {page.inner_text("body")[:300]}', flush=True)
        return []

    rows = block_table.query_selector_all('tr')
    headers = [th.inner_text().strip().lower() for th in rows[0].query_selector_all('th')]
    print(f'  Headers: {headers[:8]}', flush=True)

    blocks = []
    for row in rows[1:]:
        cells = [td.inner_text().strip() for td in row.query_selector_all('td')]
        if not cells or len(cells) < 3:
            continue

        # Build a dict from headers + cells
        d = {}
        for i, h in enumerate(headers):
            if i < len(cells):
                d[h] = cells[i]

        # Try to extract block name (first non-numeric column)
        block_name = None
        for k, v in d.items():
            if v and not v.replace(',', '').replace('.', '').replace(' ', '').isdigit():
                if len(v) > 2 and 'total' not in v.lower():
                    block_name = v.upper().strip()
                    break
        if not block_name and cells:
            block_name = cells[0].upper().strip()

        if not block_name or block_name in ('S.NO', 'SL.NO', '#', 'BLOCK NAME', 'BLOCK'):
            continue

        # Map common column names
        def get(keys):
            for k in keys:
                for hk, hv in d.items():
                    if k in hk:
                        return hv
            return None

        hh      = parse_int(get(['household', 'hh worked']))
        pd      = parse_int(get(['person.day', 'personday', 'person day']))
        women   = parse_int(get(['women']))
        exp     = parse_float(get(['expenditure', 'expend']))
        wages   = parse_float(get(['wage', 'wages']))
        works   = parse_int(get(['work taken', 'works taken']))
        comp    = parse_int(get(['complet', 'completed']))
        wage_rt = parse_float(get(['avg wage', 'average wage', 'wage rate']))

        # Compute allocation if we have approved LB
        lb = parse_int(get(['labour budget', 'approved labour']))
        alloc = round(lb * NOTIFIED_WAGE / (0.60 * 100_000), 2) if lb else None

        blocks.append({
            'block_name': block_name,
            'district': district_name,
            'households_worked': hh,
            'person_days': pd,
            'women_person_days': women,
            'total_expenditure_lakh': exp,
            'wages_lakh': wages,
            'works_taken_up': works,
            'works_completed': comp,
            'avg_wage_per_day': wage_rt,
            'approved_labour_budget': lb,
            'allocation_lakh': alloc,
        })

    print(f'  ✅ {len(blocks)} blocks found', flush=True)
    return blocks


def save_blocks(blocks, district_name):
    if not blocks:
        return 0
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    saved = 0
    for b in blocks:
        comp_pct = None
        if b['works_taken_up'] and b['works_taken_up'] > 0 and b['works_completed'] is not None:
            comp_pct = round(100.0 * b['works_completed'] / b['works_taken_up'], 1)

        c.execute('''INSERT OR REPLACE INTO fund_flow
            (scheme, year, level, entity_name, parent_entity, state,
             households_worked, person_days, women_person_days,
             total_expenditure_lakh, wages_lakh,
             works_taken_up, works_completed,
             avg_wage_per_day, approved_labour_budget, allocation_lakh,
             data_source, scraped_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
            ('NREGA', '2025-2026', 'block',
             b['block_name'], district_name, 'RAJASTHAN',
             b['households_worked'], b['person_days'], b['women_person_days'],
             b['total_expenditure_lakh'], b['wages_lakh'],
             b['works_taken_up'], b['works_completed'],
             b['avg_wage_per_day'], b['approved_labour_budget'], b['allocation_lakh'],
             'nreganarep.nic.in'))
        saved += 1

    conn.commit()
    conn.close()
    return saved


def run(target_district=None):
    districts = (
        {target_district: DISTRICT_CODES[target_district]}
        if target_district
        else DISTRICT_CODES
    )

    total_blocks = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})

        for district_name, district_code in districts.items():
            blocks = scrape_district_blocks(page, district_name, district_code)
            if blocks:
                saved = save_blocks(blocks, district_name)
                total_blocks += saved
                for b in blocks[:3]:
                    comp = b['works_completed'] or 0
                    taken = b['works_taken_up'] or 1
                    pct = round(100 * comp / taken, 1)
                    print(f'    {b["block_name"]:25s} exp=₹{(b["total_expenditure_lakh"] or 0)/100:.1f}Cr  comp={pct}%', flush=True)
                if len(blocks) > 3:
                    print(f'    ... and {len(blocks)-3} more blocks', flush=True)
            time.sleep(1)

        browser.close()

    print(f'\n✅ Total blocks saved: {total_blocks}')

    # Summary
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(DISTINCT parent_entity) FROM fund_flow WHERE level='block'")
    dists = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM fund_flow WHERE level='block'")
    total = c.fetchone()[0]
    conn.close()
    print(f'   Districts with block data: {dists}')
    print(f'   Total block rows: {total}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--district', help='Scrape single district (e.g. UDAIPUR)')
    args = parser.parse_args()

    target = args.district.upper() if args.district else None
    if target and target not in DISTRICT_CODES:
        print(f'Unknown district: {target}. Options: {list(DISTRICT_CODES.keys())}')
        sys.exit(1)

    run(target)
