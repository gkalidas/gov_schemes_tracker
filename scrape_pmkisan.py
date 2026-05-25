"""
Scrape PM-KISAN beneficiary list from pmkisan.gov.in (no login required).

Hierarchy: State → District → Sub-District → Village → Farmers
This is the ONLY scheme where individual farmer names + payment status are public.

Run:
  python3 scrape_pmkisan.py --discover                              # verify IDs
  python3 scrape_pmkisan.py --state RAJASTHAN --district UDAIPUR   # one district
  python3 scrape_pmkisan.py --state RAJASTHAN                       # full state
  python3 scrape_pmkisan.py --state RAJASTHAN --workers 3           # parallel sub-districts
  python3 scrape_pmkisan.py --state RAJASTHAN --resume              # skip already-scraped villages
"""

import sqlite3
import time
import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DB_FILE = 'scheme_tracker.db'
PORTAL_URL = 'https://pmkisan.gov.in/Rpt_BeneficiaryStatus_pub.aspx'

_db_lock    = threading.Lock()
_print_lock = threading.Lock()

def _print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

# Hardcoded IDs discovered from the live portal — update if portal changes
DROPDOWN_IDS = {
    'state':       'ContentPlaceHolder1_DropDownState',
    'district':    'ContentPlaceHolder1_DropDownDistrict',
    'subdistrict': 'ContentPlaceHolder1_DropDownSubDistrict',
    'village':     'ContentPlaceHolder1_DropDownVillage',
}


# ─── DB ────────────────────────────────────────────────────────────────────────

def init_table():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pmkisan_beneficiaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL,
        district TEXT NOT NULL,
        sub_district TEXT NOT NULL,
        village TEXT NOT NULL,
        farmer_name TEXT,
        father_name TEXT,
        installments_received INTEGER,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(state, district, sub_district, village, farmer_name, father_name)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pmkisan_district ON pmkisan_beneficiaries(state, district)')
    conn.commit()
    conn.close()
    print('pmkisan_beneficiaries table ready.')


def village_already_scraped(state, district, sub_district, village):
    """Return True if we already have at least one farmer for this village."""
    with _db_lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''SELECT 1 FROM pmkisan_beneficiaries
                     WHERE state=? AND district=? AND sub_district=? AND village=?
                     LIMIT 1''',
                  (state, district, sub_district, village))
        found = c.fetchone() is not None
        conn.close()
    return found


def save_farmers(farmers):
    if not farmers:
        return 0
    with _db_lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        saved = 0
        for f in farmers:
            try:
                c.execute('''INSERT OR REPLACE INTO pmkisan_beneficiaries
                    (state, district, sub_district, village,
                     farmer_name, father_name, installments_received)
                    VALUES (?,?,?,?,?,?,?)''',
                    (f['state'], f['district'], f['sub_district'],
                     f['village'], f['farmer_name'], f.get('father_name', ''),
                     f.get('installments_received')))
                saved += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
    return saved


# ─── PLAYWRIGHT HELPERS ────────────────────────────────────────────────────────

def get_options(page, dropdown_id):
    """Read dropdown options via JS — avoids CSS selector issues on ASP.NET pages."""
    try:
        options = page.evaluate(f'''
            () => {{
                const sel = document.getElementById('{dropdown_id}');
                if (!sel) return null;
                return Array.from(sel.options).map(o => ({{
                    value: o.value,
                    text: (o.text || o.innerText || '').trim()
                }}));
            }}
        ''')
    except Exception as e:
        print(f'  JS eval error for {dropdown_id}: {e}')
        return []

    if options is None:
        print(f'  Element #{dropdown_id} not found on page.')
        return []

    results = []
    for o in options:
        val  = (o.get('value') or '').strip()
        text = (o.get('text') or '').strip()
        if not val or val in ('0', '-1', '0;') or not text:
            continue
        if text.startswith('--') or 'select' in text.lower()[:10]:
            continue
        results.append((val, text))
    return results


def select_and_wait(page, dropdown_id, value, next_id=None):
    """Select a value via JS and wait for the cascading dropdown to populate."""
    page.evaluate(f'''
        () => {{
            const sel = document.getElementById('{dropdown_id}');
            sel.value = '{value}';
            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
            const onchange = sel.getAttribute('onchange');
            if (onchange) eval(onchange);
        }}
    ''')
    if next_id:
        try:
            page.wait_for_function(
                f"() => {{ const s = document.getElementById('{next_id}'); return s && s.options.length > 1; }}",
                timeout=15000,
            )
        except PWTimeout:
            pass
    try:
        page.wait_for_load_state('networkidle', timeout=10000)
    except PWTimeout:
        pass
    time.sleep(0.5)


def click_get_report(page):
    """Click the Get Report / Submit button."""
    for selector in [
        'input[type="submit"]',
        'input[type="button"]',
        'button[type="submit"]',
        'input[value*="Report"]',
        'input[value*="Get"]',
        'button:has-text("Get")',
    ]:
        try:
            page.click(selector, timeout=3000)
            try:
                page.wait_for_load_state('networkidle', timeout=12000)
            except PWTimeout:
                pass
            time.sleep(0.5)
            return True
        except Exception:
            continue
    return False


# ─── FARMER TABLE EXTRACTION ───────────────────────────────────────────────────

def extract_farmers(page, location):
    """Parse the results table. location = dict with state/district/etc keys."""
    tables = page.query_selector_all('table')
    for table in tables:
        rows = table.query_selector_all('tr')
        if len(rows) < 2:
            continue
        headers = [cell.inner_text().strip().lower()
                   for cell in rows[0].query_selector_all('th, td')]
        if not any('name' in h or 'farmer' in h or 'benefici' in h for h in headers):
            continue

        farmers = []
        for row in rows[1:]:
            cells = [td.inner_text().strip() for td in row.query_selector_all('td')]
            if not cells or len(cells) < 2:
                continue
            d = dict(zip(headers, cells))

            farmer_name = father_name = ''
            installments = None

            for h, v in d.items():
                if 'farmer' in h or 'benefici' in h:
                    farmer_name = v
                elif h == 'name' and not farmer_name:
                    farmer_name = v
                elif 'father' in h or 'husband' in h or 'spouse' in h:
                    father_name = v
                elif 'install' in h or 'transfer' in h or 'paid' in h:
                    try:
                        installments = int(''.join(c for c in v if c.isdigit()) or '0') or None
                    except ValueError:
                        pass

            if not farmer_name:
                for cell in cells:
                    if cell and len(cell) > 2 and not cell.replace(',', '').isdigit():
                        if cell.lower() not in ('total', 'sl.no', 's.no', '#', 'name', 'sr no'):
                            if not farmer_name:
                                farmer_name = cell
                            elif not father_name:
                                father_name = cell
                            else:
                                break

            if farmer_name and farmer_name.lower() not in ('total', 'sl.no', 's.no', '#'):
                farmers.append({
                    **location,
                    'farmer_name': farmer_name,
                    'father_name': father_name,
                    'installments_received': installments,
                })

        if farmers:
            return farmers

    return []


# ─── DISCOVER ─────────────────────────────────────────────────────────────────

def discover(page):
    """Print all select elements and their first few options — for debugging."""
    print('\nAll SELECT elements on page:')
    for sel in page.query_selector_all('select'):
        el_id   = sel.get_attribute('id') or '(no id)'
        el_name = sel.get_attribute('name') or ''
        opts = [o.inner_text().strip() for o in sel.query_selector_all('option')][:6]
        print(f'  id="{el_id}" name="{el_name}"')
        print(f'    options: {opts}')
    print()


# ─── SUB-DISTRICT WORKER (runs in its own browser) ────────────────────────────

def _scrape_subdistrict(state_val, state_text, dist_val, dist_text,
                         sd_val, sd_text, resume):
    """Scrape all villages in one sub-district. Each call owns its playwright + browser."""
    ids = DROPDOWN_IDS
    total = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')
        page = ctx.new_page()
        try:
            page.goto(PORTAL_URL, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=20000)

            try:
                page.wait_for_function(
                    f"() => {{ const s = document.getElementById('{ids['state']}'); return s && s.options.length > 1; }}",
                    timeout=15000,
                )
            except PWTimeout:
                pass

            select_and_wait(page, ids['state'], state_val, next_id=ids['district'])
            select_and_wait(page, ids['district'], dist_val, next_id=ids['subdistrict'])
            select_and_wait(page, ids['subdistrict'], sd_val, next_id=ids['village'])

            villages = get_options(page, ids['village'])
            _print(f'      {sd_text}: {len(villages)} villages')

            for vil_val, vil_text in villages:
                if resume and village_already_scraped(state_text, dist_text, sd_text, vil_text):
                    _print(f'        {vil_text}: skipped (already scraped)')
                    continue

                select_and_wait(page, ids['village'], vil_val)
                click_get_report(page)

                location = {
                    'state': state_text,
                    'district': dist_text,
                    'sub_district': sd_text,
                    'village': vil_text,
                }
                farmers = extract_farmers(page, location)
                n = save_farmers(farmers)
                total += n
                if farmers:
                    _print(f'        {vil_text}: {len(farmers)} farmers ({n} saved)')
                time.sleep(0.3)

        except Exception as e:
            _print(f'      ERROR in {sd_text}: {e}')
        finally:
            browser.close()

    return total


# ─── MAIN SCRAPER ──────────────────────────────────────────────────────────────

def scrape(target_state='RAJASTHAN', target_district=None, discover_only=False,
           resume=False, workers=1):
    init_table()

    # Use a single browser for discovery and district/sub-district enumeration
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36')
        page = ctx.new_page()
        ids = DROPDOWN_IDS

        print(f'Loading {PORTAL_URL} ...')
        try:
            page.goto(PORTAL_URL, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=20000)
        except Exception as e:
            print(f'Failed to load portal: {e}')
            browser.close()
            return

        if discover_only:
            discover(page)
            browser.close()
            return

        try:
            page.wait_for_function(
                f"() => {{ const s = document.getElementById('{ids['state']}'); return s && s.options.length > 1; }}",
                timeout=15000,
            )
        except PWTimeout:
            pass

        states = get_options(page, ids['state'])
        if not states:
            print('ERROR: Could not read state options. Run --discover.')
            browser.close()
            return

        state_match = [(v, t) for v, t in states if target_state.upper() in t.upper()]
        if not state_match:
            print(f'State "{target_state}" not found. Available: {[t for _, t in states[:10]]}')
            browser.close()
            return

        state_val, state_text = state_match[0]
        print(f'\nState: {state_text}')
        select_and_wait(page, ids['state'], state_val, next_id=ids['district'])

        districts = get_options(page, ids['district'])
        if not districts:
            print('ERROR: No districts loaded after selecting state.')
            browser.close()
            return

        if target_district:
            districts = [(v, t) for v, t in districts if target_district.upper() in t.upper()]
            if not districts:
                print(f'District "{target_district}" not found.')
                browser.close()
                return

        print(f'Districts to scrape: {len(districts)}')
        grand_total = 0

        for dist_val, dist_text in districts:
            print(f'\n  District: {dist_text}')
            select_and_wait(page, ids['district'], dist_val, next_id=ids['subdistrict'])
            subdistricts = get_options(page, ids['subdistrict'])
            print(f'    {len(subdistricts)} sub-districts (workers={workers})')

            if workers == 1:
                # Single browser path — reuse existing page
                for sd_val, sd_text in subdistricts:
                    select_and_wait(page, ids['subdistrict'], sd_val, next_id=ids['village'])
                    villages = get_options(page, ids['village'])
                    _print(f'      {sd_text}: {len(villages)} villages')

                    for vil_val, vil_text in villages:
                        if resume and village_already_scraped(state_text, dist_text, sd_text, vil_text):
                            _print(f'        {vil_text}: skipped')
                            continue

                        select_and_wait(page, ids['village'], vil_val)
                        click_get_report(page)

                        location = {
                            'state': state_text,
                            'district': dist_text,
                            'sub_district': sd_text,
                            'village': vil_text,
                        }
                        farmers = extract_farmers(page, location)
                        n = save_farmers(farmers)
                        grand_total += n
                        if farmers:
                            _print(f'        {vil_text}: {len(farmers)} farmers ({n} saved)')
                        time.sleep(0.3)
            else:
                # Parallel path — each sub-district gets its own browser
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = {
                        pool.submit(
                            _scrape_subdistrict,
                            state_val, state_text, dist_val, dist_text,
                            sd_val, sd_text, resume
                        ): sd_text
                        for sd_val, sd_text in subdistricts
                    }
                    for future in as_completed(futures):
                        sd_text = futures[future]
                        try:
                            n = future.result()
                            grand_total += n
                        except Exception as e:
                            _print(f'      ERROR {sd_text}: {e}')

        browser.close()

    print(f'\nDone. Total farmers saved: {grand_total}')
    _print_summary()


def _print_summary():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT COUNT(DISTINCT district) FROM pmkisan_beneficiaries')
    d = c.fetchone()[0]
    c.execute('SELECT COUNT(*) FROM pmkisan_beneficiaries')
    total = c.fetchone()[0]
    conn.close()
    print(f'DB: {d} districts, {total:,} farmers total')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state',    default='RAJASTHAN')
    parser.add_argument('--district', help='Single district (e.g. UDAIPUR)')
    parser.add_argument('--discover', action='store_true', help='Print all dropdown IDs and exit')
    parser.add_argument('--resume',   action='store_true', help='Skip villages already in DB')
    parser.add_argument('--workers',  type=int, default=1,
                        help='Parallel browser instances per district (default 1, try 2-3)')
    args = parser.parse_args()

    scrape(
        target_state=args.state,
        target_district=args.district,
        discover_only=args.discover,
        resume=args.resume,
        workers=args.workers,
    )
