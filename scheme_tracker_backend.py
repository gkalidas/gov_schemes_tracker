#!/usr/bin/env python3
from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3, requests
from bs4 import BeautifulSoup
import json, threading, time, logging
import background_scraper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

DB_FILE = 'scheme_tracker.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS schemes (
        id INTEGER PRIMARY KEY,
        name TEXT UNIQUE,
        ministry TEXT,
        description TEXT,
        website TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS financials (
        id INTEGER PRIMARY KEY,
        scheme_id INTEGER,
        state TEXT,
        year INTEGER,
        allocated_cr REAL,
        released_cr REAL,
        spent_cr REAL,
        beneficiaries INTEGER,
        data_source TEXT,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(scheme_id) REFERENCES schemes(id),
        UNIQUE(scheme_id, state, year)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS officers (
        id INTEGER PRIMARY KEY,
        name TEXT,
        designation TEXT,
        state TEXT,
        scheme_id INTEGER,
        ministry TEXT,
        tenure_start TEXT,
        tenure_end TEXT,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(scheme_id) REFERENCES schemes(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS discrepancies (
        id INTEGER PRIMARY KEY,
        scheme_id INTEGER,
        state TEXT,
        year INTEGER,
        discrepancy_type TEXT,
        description TEXT,
        severity TEXT,
        gap_cr REAL,
        detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(scheme_id) REFERENCES schemes(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS data_sources (
        id INTEGER PRIMARY KEY,
        scheme_id INTEGER,
        source_url TEXT,
        source_name TEXT,
        last_scraped TIMESTAMP,
        data_type TEXT,
        FOREIGN KEY(scheme_id) REFERENCES schemes(id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS news_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scheme TEXT NOT NULL,
        level TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        title TEXT,
        url TEXT UNIQUE,
        source_name TEXT,
        source_type TEXT,
        published_at TEXT,
        snippet TEXT,
        query_used TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_news_entity ON news_cache(scheme, level, entity_name)')

    c.execute('''CREATE TABLE IF NOT EXISTS social_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        scheme TEXT NOT NULL,
        level TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        title TEXT,
        url TEXT UNIQUE,
        author TEXT,
        score INTEGER,
        comments INTEGER,
        thumbnail_url TEXT,
        published_at TEXT,
        snippet TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_social_entity ON social_cache(platform, scheme, level, entity_name)')

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

init_db()

class SchemeDataCollector:
    def __init__(self):
        self.sources = {
            'PMJAY': {
                'url': 'https://pmjay.gov.in/statewise-report',
                'name': 'PM-JAY Official Dashboard',
                'type': 'health'
            },
            'NREGA': {
                'url': 'https://nrega.nic.in/netnrega/state_html/state_links_hi.html',
                'name': 'NREGA Official Portal',
                'type': 'employment'
            },
            'PMAY': {
                'url': 'https://pmaymis.gov.in/Public_FrmDashBoard.aspx',
                'name': 'PM-AY Urban Housing',
                'type': 'housing'
            },
            'PMKISAN': {
                'url': 'https://pmkisan.gov.in/BeneficiaryStatus.aspx',
                'name': 'PM-KISAN Farmer Support',
                'type': 'agriculture'
            }
        }
    
    def collect_all(self):
        logger.info("Starting data collection cycle...")
        conn = sqlite3.connect(DB_FILE)
        conn.close()
        logger.info("Data collection cycle complete")

collector = SchemeDataCollector()

def background_crawler():
    while True:
        try:
            collector.collect_all()
            time.sleep(6 * 3600)
        except Exception as e:
            logger.error(f"Crawler error: {str(e)}")
            time.sleep(60)

crawler_thread = threading.Thread(target=background_crawler, daemon=True)
crawler_thread.start()

@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'timestamp': str(__import__('datetime').datetime.now())})

@app.route('/api/schemes', methods=['GET'])
def get_schemes():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM schemes ORDER BY name')
    schemes = [dict(row) for row in c.fetchall()]
    conn.close()
    return jsonify(schemes)

@app.route('/api/dashboard', methods=['GET'])
def get_dashboard_summary():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) as count FROM schemes')
    total_schemes = dict(c.fetchone())['count']
    
    c.execute('SELECT COUNT(*) as count FROM financials')
    total_datapoints = dict(c.fetchone())['count']
    
    c.execute('SELECT SUM(beneficiaries) as total FROM financials WHERE year = (SELECT MAX(year) FROM financials)')
    total_beneficiaries = dict(c.fetchone()).get('total', 0) or 0
    
    c.execute('''SELECT f.state, s.name as scheme, ROUND(100.0 * f.spent_cr / f.allocated_cr, 1) as utilization
                 FROM financials f JOIN schemes s ON f.scheme_id=s.id
                 WHERE f.allocated_cr > 0 AND f.year='2024-25' ORDER BY utilization ASC LIMIT 10''')
    low_utilization = [dict(row) for row in c.fetchall()]

    c.execute('''SELECT COUNT(*) as count FROM financials WHERE allocated_cr > 0 AND year='2024-25' AND spent_cr / allocated_cr < 0.5''')
    major_gaps = dict(c.fetchone())['count']
    
    conn.close()
    
    return jsonify({
        'total_schemes': total_schemes,
        'total_datapoints': total_datapoints,
        'total_beneficiaries': int(total_beneficiaries),
        'low_utilization_states': low_utilization,
        'major_fund_gaps': major_gaps
    })

@app.route('/api/utilization', methods=['GET'])
def get_utilization_data():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    year = request.args.get('year', '2024-25')

    c.execute('''SELECT s.name as scheme, f.state, f.allocated_cr, f.spent_cr, f.beneficiaries,
                        ROUND(100.0 * f.spent_cr / f.allocated_cr, 1) as utilization_pct,
                        ROUND(f.allocated_cr - f.spent_cr, 2) as fund_gap
                 FROM financials f JOIN schemes s ON f.scheme_id = s.id
                 WHERE f.year = ? AND f.allocated_cr > 0 ORDER BY utilization_pct ASC''', (year,))
    
    data = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'year': year, 'data': data, 'total_records': len(data)})

@app.route('/api/state/<state_name>', methods=['GET'])
def get_state_data(state_name):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''SELECT s.name as scheme, f.year, f.allocated_cr, f.spent_cr, f.beneficiaries,
                        ROUND(100.0 * f.spent_cr / f.allocated_cr, 1) as utilization_pct
                 FROM financials f JOIN schemes s ON f.scheme_id = s.id
                 WHERE f.state = ? ORDER BY f.year DESC, s.name''', (state_name,))
    
    schemes_data = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'state': state_name, 'schemes': schemes_data})

@app.route('/api/discrepancies', methods=['GET'])
def get_discrepancies():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('''SELECT s.name as scheme, f.state, f.year, f.allocated_cr, f.spent_cr,
                        ROUND(f.allocated_cr - f.spent_cr, 2) as gap,
                        ROUND(100.0 * f.spent_cr / f.allocated_cr, 1) as utilization_pct
                 FROM financials f JOIN schemes s ON f.scheme_id = s.id
                 WHERE f.allocated_cr > 0 AND (f.spent_cr / f.allocated_cr < 0.5 OR f.spent_cr = 0)
                 ORDER BY gap DESC''')
    
    discrepancies = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'total_discrepancies': len(discrepancies), 'critical_gaps': discrepancies[:20]})

@app.route('/api/add-financial-data', methods=['POST'])
def add_financial_data():
    data = request.json
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    try:
        c.execute('''INSERT INTO financials (scheme_id, state, year, allocated_cr, released_cr, spent_cr, beneficiaries, data_source)
                    VALUES ((SELECT id FROM schemes WHERE name = ?), ?, ?, ?, ?, ?, ?, ?)''',
                (data['scheme_name'], data['state'], data['year'],
                 data.get('allocated_cr'), data.get('released_cr'),
                 data.get('spent_cr'), data.get('beneficiaries'),
                 data.get('data_source', 'Manual Entry')))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success'}), 201
    except Exception as e:
        conn.close()
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/last-crawl', methods=['GET'])
def get_last_crawl():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT MAX(scraped_at) as last_crawl FROM financials')
    result = c.fetchone()
    conn.close()
    return jsonify({'last_crawl': result[0] if result[0] else 'Never', 'next_crawl': 'In ~6 hours'})

def init_default_schemes():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    schemes = [
        ('PM-JAY', 'Ministry of Health & Family Welfare',
         'Health insurance scheme for poor households', 'https://pmjay.gov.in'),
        ('NREGA', 'Ministry of Rural Development',
         'Employment guarantee scheme', 'https://nrega.nic.in'),
        ('PMAY-U', 'Ministry of Housing & Urban Affairs',
         'Housing scheme for urban poor', 'https://pmaymis.gov.in'),
        ('PM-KISAN', 'Ministry of Agriculture',
         'Direct income support for farmers', 'https://pmkisan.gov.in'),
        ('PM Ujjwala', 'Ministry of Petroleum & Natural Gas',
         'LPG connection scheme for poor households', 'https://pmujjwala.gov.in'),
        ('Jal Jeevan Mission', 'Ministry of Jal Shakti',
         'Piped water supply scheme', 'https://jaljeevan.gov.in'),
    ]

    for name, ministry, desc, website in schemes:
        c.execute('SELECT id FROM schemes WHERE name=?', (name,))
        if not c.fetchone():
            c.execute('INSERT INTO schemes (name, ministry, description, website) VALUES (?, ?, ?, ?)',
                      (name, ministry, desc, website))

    conn.commit()
    conn.close()

init_default_schemes()
background_scraper.start(db_file=DB_FILE)

"""
MONEY TRAIL API ENDPOINTS
Add these routes to your scheme_tracker_backend.py

Copy everything below and paste it BEFORE the
    if __name__ == '__main__':
line in scheme_tracker_backend.py
"""

# ============ MONEY TRAIL ENDPOINTS ============

@app.route('/api/money-trail/<state>', methods=['GET'])
def get_money_trail(state):
    """Get full money trail: state → districts with officer accountability"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # State level summary
    c.execute('''SELECT * FROM fund_flow
                 WHERE scheme = 'NREGA' AND level = 'state' AND entity_name = ?''',
              (state.upper(),))
    state_row = c.fetchone()
    state_data = dict(state_row) if state_row else None

    # All districts
    c.execute('''SELECT * FROM fund_flow
                 WHERE scheme = 'NREGA' AND level = 'district' AND state = ?
                 ORDER BY total_expenditure_lakh DESC''',
              (state.upper(),))
    districts = [dict(row) for row in c.fetchall()]

    # Add completion rate to each district
    for d in districts:
        if d['works_taken_up'] and d['works_taken_up'] > 0:
            d['completion_pct'] = round(100.0 * (d['works_completed'] or 0) / d['works_taken_up'], 1)
        else:
            d['completion_pct'] = 0

        if d['person_days'] and d['person_days'] > 0 and d['women_person_days']:
            d['women_pct'] = round(100.0 * d['women_person_days'] / d['person_days'], 1)
        else:
            d['women_pct'] = 0

        if d.get('allocation_lakh') and d.get('total_expenditure_lakh'):
            d['unspent_lakh'] = round(d['allocation_lakh'] - d['total_expenditure_lakh'], 2)
            d['utilization_pct'] = round(100.0 * d['total_expenditure_lakh'] / d['allocation_lakh'], 1)
        else:
            d['unspent_lakh'] = None
            d['utilization_pct'] = None

    # Officers
    c.execute('''SELECT * FROM officers
                 WHERE scheme = 'NREGA'
                 ORDER BY CASE level
                    WHEN 'centre' THEN 1
                    WHEN 'state' THEN 2
                    WHEN 'district' THEN 3
                    WHEN 'block' THEN 4
                 END''')
    officers = [dict(row) for row in c.fetchall()]

    conn.close()

    return jsonify({
        'state': state.upper(),
        'scheme': 'NREGA',
        'state_summary': state_data,
        'districts': districts,
        'officers': officers,
        'total_districts': len(districts)
    })


@app.route('/api/money-trail/<state>/<district>', methods=['GET'])
def get_district_detail(state, district):
    """Get detailed data for one district"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    district_name = district.upper().replace('-', ' ')

    c.execute('''SELECT * FROM fund_flow
                 WHERE scheme = 'NREGA' AND level = 'district'
                 AND entity_name = ? AND state = ?''',
              (district_name, state.upper()))
    data = c.fetchone()

    # Get officer for this district
    c.execute('''SELECT * FROM officers
                 WHERE entity = ? AND state = ?''',
              (district_name, state.upper()))
    officer = c.fetchone()

    conn.close()

    if not data:
        return jsonify({'error': f'No data for {district_name}'}), 404

    d = dict(data)

    # Computed fields
    if d['works_taken_up'] and d['works_taken_up'] > 0:
        d['completion_pct'] = round(100.0 * (d['works_completed'] or 0) / d['works_taken_up'], 1)
    else:
        d['completion_pct'] = 0

    if d['person_days'] and d['person_days'] > 0:
        d['women_pct'] = round(100.0 * (d['women_person_days'] or 0) / d['person_days'], 1)
        d['st_pct'] = round(100.0 * (d['st_person_days'] or 0) / d['person_days'], 1)
        d['sc_pct'] = round(100.0 * (d['sc_person_days'] or 0) / d['person_days'], 1)
    else:
        d['women_pct'] = d['st_pct'] = d['sc_pct'] = 0

    # Cost per household
    if d['households_worked'] and d['households_worked'] > 0 and d['total_expenditure_lakh']:
        d['cost_per_household'] = round(d['total_expenditure_lakh'] * 100000 / d['households_worked'], 0)
    else:
        d['cost_per_household'] = 0

    # Allocation gap
    if d.get('allocation_lakh') and d.get('total_expenditure_lakh'):
        d['unspent_lakh'] = round(d['allocation_lakh'] - d['total_expenditure_lakh'], 2)
        d['utilization_pct'] = round(100.0 * d['total_expenditure_lakh'] / d['allocation_lakh'], 1)
    else:
        d['unspent_lakh'] = None
        d['utilization_pct'] = None

    return jsonify({
        'district': d,
        'officer': dict(officer) if officer else None
    })


@app.route('/api/money-trail/<state>/<district>/blocks', methods=['GET'])
def get_block_data(state, district):
    """Get block-level breakdown for a district (if scraped)"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    district_name = district.upper().replace('-', ' ')
    c.execute('''SELECT entity_name, total_expenditure_lakh, allocation_lakh,
                        households_worked, person_days, works_taken_up,
                        works_completed, avg_wage_per_day, women_person_days
                 FROM fund_flow
                 WHERE scheme = 'NREGA' AND level = 'block' AND parent_entity = ?
                 ORDER BY total_expenditure_lakh DESC NULLS LAST''',
              (district_name,))

    blocks = []
    for row in c.fetchall():
        b = dict(row)
        if b['works_taken_up'] and b['works_taken_up'] > 0:
            b['completion_pct'] = round(100.0 * (b['works_completed'] or 0) / b['works_taken_up'], 1)
        else:
            b['completion_pct'] = None
        if b['allocation_lakh'] and b['total_expenditure_lakh']:
            b['utilization_pct'] = round(100.0 * b['total_expenditure_lakh'] / b['allocation_lakh'], 1)
        else:
            b['utilization_pct'] = None
        blocks.append(b)

    conn.close()
    return jsonify({'district': district_name, 'blocks': blocks, 'count': len(blocks)})


@app.route('/api/rankings', methods=['GET'])
def get_rankings():
    """Get district rankings by various metrics"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    metric = request.args.get('metric', 'expenditure')

    if metric == 'expenditure':
        order = 'total_expenditure_lakh DESC'
    elif metric == 'completion':
        order = 'CAST(works_completed AS REAL) / NULLIF(works_taken_up, 0) ASC'
    elif metric == 'wage':
        order = 'avg_wage_per_day ASC'
    elif metric == 'employment':
        order = 'avg_days_per_household DESC'
    elif metric == 'women':
        order = 'CAST(women_person_days AS REAL) / NULLIF(person_days, 0) DESC'
    else:
        order = 'total_expenditure_lakh DESC'

    c.execute(f'''SELECT entity_name, total_expenditure_lakh, wages_lakh,
                         material_lakh, admin_lakh, households_worked,
                         person_days, women_person_days, avg_wage_per_day,
                         avg_days_per_household, works_taken_up, works_completed,
                         hh_completed_100_days, officer_name
                  FROM fund_flow
                  WHERE scheme = 'NREGA' AND level = 'district' AND state = 'RAJASTHAN'
                  ORDER BY {order}''')

    districts = []
    for row in c.fetchall():
        d = dict(row)
        if d['works_taken_up'] and d['works_taken_up'] > 0:
            d['completion_pct'] = round(100.0 * (d['works_completed'] or 0) / d['works_taken_up'], 1)
        else:
            d['completion_pct'] = 0
        districts.append(d)

    conn.close()

    return jsonify({
        'metric': metric,
        'districts': districts
    })


@app.route('/api/red-flags', methods=['GET'])
def get_red_flags():
    """Auto-detect and return anomalies across all districts"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute('''SELECT * FROM fund_flow
                 WHERE scheme = 'NREGA' AND level = 'district' AND state = 'RAJASTHAN' ''')

    flags = []
    for row in c.fetchall():
        d = dict(row)
        name = d['entity_name']

        # Flag 1: Very low work completion rate
        if d['works_taken_up'] and d['works_taken_up'] > 0:
            completion = 100.0 * (d['works_completed'] or 0) / d['works_taken_up']
            if completion < 15:
                flags.append({
                    'district': name,
                    'type': 'LOW_COMPLETION',
                    'severity': 'CRITICAL' if completion < 8 else 'HIGH',
                    'detail': f"Only {completion:.1f}% works completed ({d['works_completed']:,} of {d['works_taken_up']:,})",
                    'value': round(completion, 1)
                })

        # Flag 2: Low average days of employment
        if d['avg_days_per_household'] and d['avg_days_per_household'] < 30:
            flags.append({
                'district': name,
                'type': 'LOW_EMPLOYMENT',
                'severity': 'HIGH',
                'detail': f"Average only {d['avg_days_per_household']:.0f} days/household (target: 100 days)",
                'value': d['avg_days_per_household']
            })

        # Flag 3: High admin expenditure ratio
        if d['total_expenditure_lakh'] and d['total_expenditure_lakh'] > 0 and d['admin_lakh']:
            admin_pct = 100.0 * d['admin_lakh'] / d['total_expenditure_lakh']
            if admin_pct > 5:
                flags.append({
                    'district': name,
                    'type': 'HIGH_ADMIN_COST',
                    'severity': 'MEDIUM',
                    'detail': f"Admin cost is {admin_pct:.1f}% of total expenditure",
                    'value': round(admin_pct, 1)
                })

        # Flag 4: Very low wage rate
        if d['avg_wage_per_day'] and d['avg_wage_per_day'] < 220:
            flags.append({
                'district': name,
                'type': 'LOW_WAGE',
                'severity': 'HIGH',
                'detail': f"Average wage ₹{d['avg_wage_per_day']:.0f}/day vs notified ₹266/day",
                'value': d['avg_wage_per_day']
            })

        # Flag 5: Very few households completing 100 days
        if d['households_worked'] and d['households_worked'] > 0 and d['hh_completed_100_days'] is not None:
            pct_100 = 100.0 * d['hh_completed_100_days'] / d['households_worked']
            if pct_100 < 3:
                flags.append({
                    'district': name,
                    'type': 'LOW_100_DAYS',
                    'severity': 'HIGH',
                    'detail': f"Only {d['hh_completed_100_days']:,} of {d['households_worked']:,} households got 100 days ({pct_100:.1f}%)",
                    'value': round(pct_100, 1)
                })

    conn.close()

    # Sort by severity
    severity_order = {'CRITICAL': 0, 'HIGH': 1, 'MEDIUM': 2, 'LOW': 3}
    flags.sort(key=lambda x: severity_order.get(x['severity'], 99))

    return jsonify({
        'total_flags': len(flags),
        'flags': flags
    })


@app.route('/api/mindmap/schemes', methods=['GET'])
def mindmap_schemes():
    """Scheme-level aggregates for mind map initial nodes."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''SELECT s.id, s.name, s.description, s.ministry, s.website,
                        COUNT(DISTINCT f.state) as state_count,
                        ROUND(SUM(f.allocated_cr), 0) as total_allocated,
                        ROUND(SUM(f.spent_cr), 0) as total_spent,
                        SUM(f.beneficiaries) as total_beneficiaries,
                        ROUND(100.0 * SUM(f.spent_cr) / NULLIF(SUM(f.allocated_cr), 0), 1) as utilization_pct
                 FROM schemes s
                 LEFT JOIN financials f ON f.scheme_id = s.id
                    AND f.year = (SELECT MAX(year) FROM financials f2
                                  WHERE f2.scheme_id = s.id AND f2.state = f.state)
                 GROUP BY s.id ORDER BY s.name''')
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


@app.route('/api/officers', methods=['GET'])
def get_officers_query():
    """Officer lookup with optional filters: state, level, scheme."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    state  = request.args.get('state', '').upper()
    level  = request.args.get('level', '')
    scheme = request.args.get('scheme', '')
    q = 'SELECT * FROM officers WHERE 1=1'
    params = []
    if state:
        q += ' AND UPPER(state)=?'; params.append(state)
    if level:
        q += ' AND level=?'; params.append(level)
    if scheme:
        q += ' AND scheme=?'; params.append(scheme)
    c.execute(q, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(rows)


# District code map for direct nreganarep.nic.in district report URLs
NREGA_DISTRICT_CODES = {
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

# Scheme-level official sources — only links verified to be reachable/useful
# Note: nreganarep.nic.in has CAPTCHA for bots but works in a browser
OFFICIAL_SOURCES = {
    'NREGA': [
        {
            'name': 'NREGA MIS Portal (navigate in browser)',
            'url': 'https://nrega.nic.in/netnrega/home.aspx',
            'description': 'Main portal — go to Reports → State/District for live expenditure data. CAPTCHA blocks direct scraping.',
        },
        {
            'name': 'CAG Audit — Rural Development',
            'url': 'https://cag.gov.in/en/audit-report?sector=social&subsector=Rural+Development',
            'description': 'Comptroller & Auditor General findings on MGNREGS fund misuse and irregularities',
        },
        {
            'name': 'data.gov.in — NREGA search',
            'url': 'https://data.gov.in/search?title=MGNREGA',
            'description': 'Open data platform — downloadable CSVs for district/block level data',
        },
        {
            'name': 'Ministry of Rural Development',
            'url': 'https://rural.gov.in/en/publication-reports',
            'description': 'Annual reports with state-wise allocation and scheme performance',
        },
    ],
    'PM-JAY': [
        {
            'name': 'PM-JAY Dashboard',
            'url': 'https://pmjay.gov.in',
            'description': 'State-wise claims, beneficiaries, hospital empanelment data',
        },
        {
            'name': 'CAG Audit — Health',
            'url': 'https://cag.gov.in/en/audit-report?sector=social&subsector=Health',
            'description': 'CAG findings on PM-JAY implementation and fund utilization',
        },
    ],
    'PM-KISAN': [
        {
            'name': 'PM-KISAN Beneficiary Dashboard',
            'url': 'https://pmkisan.gov.in/Dashboardnew.aspx',
            'description': 'Live installment transfer stats and beneficiary count by state',
        },
        {
            'name': 'PM-KISAN Beneficiary Status (State → Village)',
            'url': 'https://pmkisan.gov.in/BeneficiaryStatus.aspx',
            'description': 'The only scheme with public individual-level data — drill to village',
        },
    ],
    'PMAY-U': [
        {
            'name': 'PMAY-U Progress Dashboard',
            'url': 'https://pmaymis.gov.in/Public_FrmDashBoard.aspx',
            'description': 'Houses sanctioned vs grounded vs completed by state',
        },
        {
            'name': 'CAG Audit — Housing',
            'url': 'https://cag.gov.in/en/audit-report?sector=social',
            'description': 'CAG findings on PMAY-U fund utilization and beneficiary selection',
        },
    ],
    'PM Ujjwala': [
        {
            'name': 'PM Ujjwala Portal',
            'url': 'https://pmujjwala.gov.in',
            'description': 'LPG connection data by state under PMUY 1.0 and 2.0',
        },
    ],
    'Jal Jeevan Mission': [
        {
            'name': 'JJM District-wise Tap Connections',
            'url': 'https://ejalshakti.gov.in/jjmreport/JJMIndia.aspx',
            'description': 'Live: functional household tap connection % by district',
        },
        {
            'name': 'JJM State Dashboard',
            'url': 'https://ejalshakti.gov.in/jjmreport/JJMByState.aspx',
            'description': 'State-level water supply coverage — the data source we scraped',
        },
    ],
}


@app.route('/api/refresh', methods=['POST'])
def refresh_sources():
    """On-demand fetch: pull latest news + social for a specific entity and update DB."""
    entity = request.args.get('entity', '').upper().strip()
    level  = request.args.get('level', 'district')
    scheme = request.args.get('scheme', 'NREGA')

    if not entity:
        return jsonify({'error': 'entity is required'}), 400

    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))

    saved_news = 0
    saved_social = 0

    try:
        import fetch_news as fn
        fn.init_news_table()
        if level == 'district':
            saved_news = fn.fetch_for_district(entity, scheme)
        else:
            saved_news = fn.fetch_for_state(entity, scheme)
    except Exception as e:
        logger.error(f'refresh news error: {e}')

    try:
        import fetch_social as fs
        fs.init_social_table()
        from fetch_social import reddit_posts_for, save_posts
        posts = reddit_posts_for(entity, scheme, level)
        saved_social = save_posts(posts)
    except Exception as e:
        logger.error(f'refresh social error: {e}')

    return jsonify({'entity': entity, 'level': level, 'scheme': scheme,
                    'saved_news': saved_news, 'saved_social': saved_social})


@app.route('/api/sources', methods=['GET'])
def get_sources():
    """Return official sources + cached news articles for a scheme/entity/level."""
    entity = request.args.get('entity', '').upper().strip()
    level  = request.args.get('level', 'district')
    scheme = request.args.get('scheme', 'NREGA')

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    news = []
    if entity:
        c.execute('''SELECT title, url, source_name, source_type, published_at, snippet
                     FROM news_cache
                     WHERE UPPER(entity_name) = ? AND scheme = ? AND level = ?
                     ORDER BY fetched_at DESC LIMIT 30''',
                  (entity, scheme, level))
        news = [dict(r) for r in c.fetchall()]

    # Also include state-level news when viewing a district
    state_news = []
    if level == 'district':
        c.execute('''SELECT title, url, source_name, source_type, published_at, snippet
                     FROM news_cache
                     WHERE level = 'state' AND scheme = ? AND UPPER(entity_name) = 'RAJASTHAN'
                     ORDER BY fetched_at DESC LIMIT 10''',
                  (scheme,))
        state_news = [dict(r) for r in c.fetchall()]

    conn.close()

    all_news = news + [n for n in state_news if n['url'] not in {x['url'] for x in news}]

    # Social media results
    social = []
    if entity:
        conn2 = sqlite3.connect(DB_FILE)
        conn2.row_factory = sqlite3.Row
        c2 = conn2.cursor()
        c2.execute('''SELECT platform, title, url, author, score, comments,
                             thumbnail_url, published_at, snippet
                      FROM social_cache
                      WHERE UPPER(entity_name) = ? AND scheme = ? AND level = ?
                      ORDER BY score DESC, fetched_at DESC LIMIT 20''',
                   (entity, scheme, level))
        social = [dict(r) for r in c2.fetchall()]
        conn2.close()

    official = list(OFFICIAL_SOURCES.get(scheme, []))  # copy; don't mutate the dict

    # For a specific NREGA district, prepend a direct link to that district's live MIS report
    if scheme == 'NREGA' and level == 'district' and entity in NREGA_DISTRICT_CODES:
        code = NREGA_DISTRICT_CODES[entity]
        direct_url = (
            f'https://nreganarep.nic.in/netnrega/homestciti.aspx'
            f'?state_code=27&state_name=RAJASTHAN'
            f'&district_code={code}&district_name={entity}'
        )
        official = [{
            'name': f'NREGA MIS — {entity.title()} District (Live)',
            'url': direct_url,
            'description': f'Direct link: live NREGA data for {entity.title()} — works, wages, households, person-days',
        }] + official

    return jsonify({
        'entity': entity,
        'level': level,
        'scheme': scheme,
        'official': official,
        'national_news': [n for n in all_news if n['source_type'] == 'national_news'],
        'local_news': [n for n in all_news if n['source_type'] == 'local_news'],
        'social': social,
        'total_articles': len(all_news),
        'has_news': len(all_news) > 0,
    })


# ============ PM-KISAN BENEFICIARY ENDPOINTS ============

@app.route('/api/pmkisan/summary', methods=['GET'])
def pmkisan_summary():
    """Total farmers + district breakdown from scraped data."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT COUNT(*) as total FROM pmkisan_beneficiaries')
    total = dict(c.fetchone())['total']
    c.execute('''SELECT state, district,
                        COUNT(*) as farmer_count,
                        COUNT(DISTINCT village) as villages,
                        COUNT(DISTINCT sub_district) as sub_districts,
                        ROUND(AVG(installments_received), 1) as avg_installments
                 FROM pmkisan_beneficiaries
                 GROUP BY state, district
                 ORDER BY farmer_count DESC''')
    districts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({
        'total_farmers': total,
        'districts': districts,
        'has_data': total > 0,
    })


@app.route('/api/pmkisan/villages', methods=['GET'])
def pmkisan_villages():
    """Villages (with farmer counts) for a state+district+sub_district."""
    state       = request.args.get('state', 'RAJASTHAN')
    district    = request.args.get('district', '')
    sub_district = request.args.get('sub_district', '')
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if sub_district:
        c.execute('''SELECT sub_district, village, COUNT(*) as farmer_count
                     FROM pmkisan_beneficiaries
                     WHERE state=? AND district=? AND sub_district=?
                     GROUP BY village ORDER BY village''',
                  (state, district, sub_district))
    elif district:
        c.execute('''SELECT sub_district, COUNT(DISTINCT village) as villages,
                            COUNT(*) as farmer_count
                     FROM pmkisan_beneficiaries
                     WHERE state=? AND district=?
                     GROUP BY sub_district ORDER BY sub_district''',
                  (state, district))
    else:
        c.execute('''SELECT district, COUNT(DISTINCT sub_district) as sub_districts,
                            COUNT(DISTINCT village) as villages,
                            COUNT(*) as farmer_count
                     FROM pmkisan_beneficiaries
                     WHERE state=?
                     GROUP BY district ORDER BY farmer_count DESC''',
                  (state,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify({'rows': rows, 'count': len(rows)})


@app.route('/api/pmkisan/beneficiaries', methods=['GET'])
def pmkisan_beneficiaries():
    """Individual farmer list for a village (or district/sub-district)."""
    state        = request.args.get('state', '')
    district     = request.args.get('district', '')
    sub_district = request.args.get('sub_district', '')
    village      = request.args.get('village', '')
    search       = request.args.get('search', '').strip()
    limit        = min(int(request.args.get('limit', 200)), 500)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    q = 'SELECT * FROM pmkisan_beneficiaries WHERE 1=1'
    params = []
    if state:        q += ' AND state=?';        params.append(state)
    if district:     q += ' AND district=?';     params.append(district)
    if sub_district: q += ' AND sub_district=?'; params.append(sub_district)
    if village:      q += ' AND village=?';      params.append(village)
    if search:
        q += ' AND (farmer_name LIKE ? OR father_name LIKE ?)';
        params += [f'%{search}%', f'%{search}%']
    q += ' ORDER BY farmer_name LIMIT ?'
    params.append(limit)

    c.execute(q, params)
    farmers = [dict(r) for r in c.fetchall()]

    c.execute('SELECT COUNT(*) FROM pmkisan_beneficiaries WHERE 1=1' +
              (' AND state=?' if state else '') +
              (' AND district=?' if district else '') +
              (' AND sub_district=?' if sub_district else '') +
              (' AND village=?' if village else ''),
              [p for p in [state, district, sub_district, village] if p])
    total = c.fetchone()[0]
    conn.close()

    return jsonify({
        'farmers': farmers,
        'returned': len(farmers),
        'total': total,
        'limit': limit,
    })


@app.route('/api/scraper/status', methods=['GET'])
def scraper_status():
    return jsonify(background_scraper.queue_status())


if __name__ == '__main__':
    print("=" * 60)
    print("Government Scheme Transparency Tracker - Backend Server")
    print("=" * 60)
    print(f"Database: {DB_FILE}")
    print("Background scraper: running (resumes automatically on restart)")
    print("Starting Flask API server on http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
