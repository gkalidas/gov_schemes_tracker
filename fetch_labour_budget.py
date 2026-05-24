"""
Fetch 'Approved labour budget' (person-days) from DeshSeva for all 33 Rajasthan districts,
then compute allocation_lakh using the NREGA 60:40 wage:material formula.

  allocation_lakh = approved_LB_days × notified_wage / (0.60 × 1_00_000)

Run: python3 fetch_labour_budget.py
"""

import sqlite3
import time
import requests
from bs4 import BeautifulSoup

DB_FILE = 'scheme_tracker.db'
NOTIFIED_WAGE = 266  # Rajasthan 2025-26 notified wage (₹/day)

DISTRICT_SLUGS = [
    'ajmer', 'alwar', 'banswara', 'baran', 'barmer', 'bharatpur', 'bhilwara',
    'bikaner', 'bundi', 'chittorgarh', 'churu', 'dausa', 'dholpur', 'dungarpur',
    'hanumangarh', 'jaipur', 'jaisalmer', 'jalore', 'jhalawar', 'jhunjhunu',
    'jodhpur', 'karauli', 'kota', 'nagaur', 'pali', 'pratapgarh', 'rajsamand',
    'sawai-madhopur', 'sikar', 'sirohi', 'sri-ganganagar', 'tonk', 'udaipur',
]

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}


def fetch_approved_lb(slug):
    url = f"https://deshseva.in/tools/mgnrega/rajasthan/{slug}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        r.raise_for_status()
    except Exception as e:
        print(f"  ❌ {slug}: {e}")
        return None

    soup = BeautifulSoup(r.text, 'html.parser')
    table = soup.find('table')
    if not table:
        return None

    for row in table.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            key = cells[0].get_text(strip=True).lower()
            if 'approved labour budget' in key:
                raw = cells[1].get_text(strip=True).replace(',', '')
                try:
                    return int(float(raw))
                except ValueError:
                    return None
    return None


def run():
    updated = 0
    failed = []

    for slug in DISTRICT_SLUGS:
        district = slug.upper().replace('-', ' ')
        lb = fetch_approved_lb(slug)

        if lb is None:
            print(f"  ⚠️  {district}: no data", flush=True)
            failed.append(district)
        else:
            allocation = round(lb * NOTIFIED_WAGE / (0.60 * 100_000), 2)
            # commit per district so progress is visible and partial runs are saved
            conn = sqlite3.connect(DB_FILE)
            conn.execute('''UPDATE fund_flow
                            SET approved_labour_budget = ?, allocation_lakh = ?
                            WHERE scheme = 'NREGA' AND level = 'district' AND entity_name = ?''',
                         (lb, allocation, district))
            conn.commit()
            conn.close()
            print(f"  ✅ {district:20s} LB={lb:>12,}  alloc=₹{allocation/100:.0f} Cr", flush=True)
            updated += 1

        time.sleep(0.3)

    print(f"\n{'='*50}")
    print(f"Updated: {updated}/33 districts")
    if failed:
        print(f"Failed:  {failed}")

    # Quick summary
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''SELECT entity_name, allocation_lakh, total_expenditure_lakh
                 FROM fund_flow WHERE level='district' AND allocation_lakh IS NOT NULL
                 ORDER BY (allocation_lakh - total_expenditure_lakh) DESC LIMIT 5''')
    print("\nTop 5 districts by unspent allocation:")
    print(f"  {'District':20s} {'Allocated':>12} {'Spent':>12} {'Gap':>12}")
    for row in c.fetchall():
        name, alloc, spent = row
        gap = (alloc or 0) - (spent or 0)
        print(f"  {name:20s} ₹{alloc/100:>8.0f} Cr  ₹{spent/100:>8.0f} Cr  ₹{gap/100:>8.0f} Cr")
    conn.close()


if __name__ == '__main__':
    run()
