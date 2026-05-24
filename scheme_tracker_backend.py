#!/usr/bin/env python3
from flask import Flask, jsonify, request
from flask_cors import CORS
import sqlite3, requests
from bs4 import BeautifulSoup
import json, threading, time, logging

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


if __name__ == '__main__':
    print("=" * 60)
    print("Government Scheme Transparency Tracker - Backend Server")
    print("=" * 60)
    print(f"Database: {DB_FILE}")
    print("Crawler: Running in background (every 6 hours)")
    print("Starting Flask API server on http://localhost:5000")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=False)
