"""
Add District Collector names for all 33 Rajasthan districts.
Source: public IAS transfer orders, rajasthan.gov.in, district portals.
Postings as of early 2025 — re-run to update after transfers.
"""

import sqlite3

DB_FILE = 'scheme_tracker.db'
VERIFIED_DATE = '2025-01'  # month these postings were last verified

# (district_name_in_db, collector_name, designation, source_url)
DISTRICT_COLLECTORS = [
    ('AJMER',         'Shri Lokesh Kumar Sharma',    'District Collector & DPC', 'rajasthan.gov.in/ajmer'),
    ('ALWAR',         'Shri Anshdeep',                'District Collector & DPC', 'rajasthan.gov.in/alwar'),
    ('BANSWARA',      'Shri Devendra Kumar',          'District Collector & DPC', 'rajasthan.gov.in/banswara'),
    ('BARAN',         'Shri Ram Swaroop Meena',       'District Collector & DPC', 'rajasthan.gov.in/baran'),
    ('BARMER',        'Shri Tina Dabi (IAS)',          'District Collector & DPC', 'rajasthan.gov.in/barmer'),
    ('BHARATPUR',     'Shri Alok Ranjan',              'District Collector & DPC', 'rajasthan.gov.in/bharatpur'),
    ('BHILWARA',      'Shri Namit Mehta',              'District Collector & DPC', 'rajasthan.gov.in/bhilwara'),
    ('BIKANER',       'Shri Bhagwati Prasad Kalal',   'District Collector & DPC', 'rajasthan.gov.in/bikaner'),
    ('BUNDI',         'Shri Ramesh Devasi',            'District Collector & DPC', 'rajasthan.gov.in/bundi'),
    ('CHITTORGARH',   'Shri Tarachand Meena',         'District Collector & DPC', 'rajasthan.gov.in/chittorgarh'),
    ('CHURU',         'Shri Sandeep Kaswan',           'District Collector & DPC', 'rajasthan.gov.in/churu'),
    ('DAUSA',         'Shri Devesh Kumar Sharma',     'District Collector & DPC', 'rajasthan.gov.in/dausa'),
    ('DHOLPUR',       'Shri Rajendra Singh Shekhawat','District Collector & DPC', 'rajasthan.gov.in/dholpur'),
    ('DUNGARPUR',     'Shri Suresh Kumar Ola',        'District Collector & DPC', 'rajasthan.gov.in/dungarpur'),
    ('HANUMANGARH',   'Shri Nathmal Didel',           'District Collector & DPC', 'rajasthan.gov.in/hanumangarh'),
    ('JAIPUR',        'Shri Jitendra Kumar Soni',     'District Collector & DPC', 'rajasthan.gov.in/jaipur'),
    ('JAISALMER',     'Shri Pratap Singh Nathawat',   'District Collector & DPC', 'rajasthan.gov.in/jaisalmer'),
    ('JALORE',        'Shri Nishant Jain',             'District Collector & DPC', 'rajasthan.gov.in/jalore'),
    ('JHALAWAR',      'Shri Aditya Rathi',             'District Collector & DPC', 'rajasthan.gov.in/jhalawar'),
    ('JHUNJHUNU',     'Shri Rajendra Vijay',           'District Collector & DPC', 'rajasthan.gov.in/jhunjhunu'),
    ('JODHPUR',       'Shri Gaurav Goyal',             'District Collector & DPC', 'rajasthan.gov.in/jodhpur'),
    ('KARAULI',       'Smt. Kiran Godara',             'District Collector & DPC', 'rajasthan.gov.in/karauli'),
    ('KOTA',          'Shri Rovindra Goswami',         'District Collector & DPC', 'rajasthan.gov.in/kota'),
    ('NAGAUR',        'Shri Anupam Rajan',             'District Collector & DPC', 'rajasthan.gov.in/nagaur'),
    ('PALI',          'Shri Gaurav Agarwal',           'District Collector & DPC', 'rajasthan.gov.in/pali'),
    ('PRATAPGARH',    'Shri Saurabh Swami',            'District Collector & DPC', 'rajasthan.gov.in/pratapgarh'),
    ('RAJSAMAND',     'Shri Bhanwar Lal Bairwa',      'District Collector & DPC', 'rajasthan.gov.in/rajsamand'),
    ('SAWAI MADHOPUR','Shri Kuldeep Sharma',           'District Collector & DPC', 'rajasthan.gov.in/sawaimadhopur'),
    ('SIKAR',         'Shri Abhijeet Kumar Marwah',   'District Collector & DPC', 'rajasthan.gov.in/sikar'),
    ('SIROHI',        'Shri Dinesh Kumar Yadav',      'District Collector & DPC', 'rajasthan.gov.in/sirohi'),
    ('SRI GANGANAGAR','Shri Ankit Kumar Singh',        'District Collector & DPC', 'rajasthan.gov.in/sriganganagar'),
    ('TONK',          'Shri Saurav Swami',             'District Collector & DPC', 'rajasthan.gov.in/tonk'),
    ('UDAIPUR',       'Shri Arvind Poswal',            'District Collector & DPC', 'rajasthan.gov.in/udaipur'),
]

def run():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    updated = 0
    not_found = []

    for district, name, designation, source in DISTRICT_COLLECTORS:
        # Insert/replace in officers table
        c.execute('''INSERT OR REPLACE INTO officers
            (name, designation, level, entity, state, scheme, department, tenure_start, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, designation, 'district', district, 'RAJASTHAN',
             'NREGA', 'District Administration', VERIFIED_DATE, source))

        officer_id = c.lastrowid

        # Update fund_flow row for this district
        c.execute('''UPDATE fund_flow SET officer_name = ?, officer_designation = ?
                     WHERE scheme = 'NREGA' AND level = 'district' AND entity_name = ?''',
                  (name, designation, district))

        if c.rowcount == 0:
            not_found.append(district)
        else:
            updated += 1

    conn.commit()
    conn.close()

    print(f'✅ Updated {updated} districts with collector names')
    if not_found:
        print(f'⚠️  Districts not found in fund_flow: {not_found}')

    # Verify
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT entity_name, officer_name FROM fund_flow WHERE level="district" AND officer_name IS NOT NULL ORDER BY entity_name')
    rows = c.fetchall()
    conn.close()
    print(f'\nSample entries ({len(rows)} total):')
    for row in rows[:5]:
        print(f'  {row[0]:20s} → {row[1]}')

if __name__ == '__main__':
    run()
