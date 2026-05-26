#!/usr/bin/env python3
import sqlite3

from config import DB_FILE

SAMPLE_DATA = [
    ('PM-JAY', 'Andhra Pradesh', 2024, 450, 420, 350, 2500000, 'pmjay.gov.in'),
    ('PM-JAY', 'Maharashtra', 2024, 380, 360, 330, 2100000, 'pmjay.gov.in'),
    ('PM-JAY', 'Uttar Pradesh', 2024, 920, 850, 380, 1800000, 'pmjay.gov.in'),
    ('PM-JAY', 'Bihar', 2024, 300, 200, 45, 250000, 'pmjay.gov.in'),
    ('PM-JAY', 'Rajasthan', 2024, 290, 250, 180, 1200000, 'pmjay.gov.in'),
    ('PM-JAY', 'Madhya Pradesh', 2024, 350, 320, 200, 1400000, 'pmjay.gov.in'),
    ('PM-JAY', 'Karnataka', 2024, 280, 265, 240, 1600000, 'pmjay.gov.in'),
    ('PM-JAY', 'Gujarat', 2024, 320, 300, 280, 1900000, 'pmjay.gov.in'),
    ('NREGA', 'Andhra Pradesh', 2024, 2500, 2400, 1800, 45000000, 'nrega.nic.in'),
    ('NREGA', 'Maharashtra', 2024, 1800, 1700, 1500, 38000000, 'nrega.nic.in'),
    ('NREGA', 'Uttar Pradesh', 2024, 3200, 3000, 1500, 42000000, 'nrega.nic.in'),
    ('NREGA', 'Bihar', 2024, 2100, 1900, 900, 28000000, 'nrega.nic.in'),
    ('NREGA', 'Rajasthan', 2024, 2800, 2600, 2200, 55000000, 'nrega.nic.in'),
    ('NREGA', 'Odisha', 2024, 2600, 2400, 2000, 48000000, 'nrega.nic.in'),
    ('PMAY-U', 'Maharashtra', 2024, 5000, 4500, 3800, 500000, 'pmaymis.gov.in'),
    ('PMAY-U', 'Uttar Pradesh', 2024, 8000, 7200, 3500, 450000, 'pmaymis.gov.in'),
    ('PMAY-U', 'Gujarat', 2024, 4000, 3600, 3200, 400000, 'pmaymis.gov.in'),
    ('PMAY-U', 'Rajasthan', 2024, 3500, 3000, 2200, 300000, 'pmaymis.gov.in'),
    ('PMAY-U', 'Karnataka', 2024, 3000, 2700, 2400, 350000, 'pmaymis.gov.in'),
    ('PM-KISAN', 'Uttar Pradesh', 2024, 8500, 8200, 7800, 21000000, 'pmkisan.gov.in'),
    ('PM-KISAN', 'Madhya Pradesh', 2024, 7200, 6800, 6200, 16500000, 'pmkisan.gov.in'),
    ('PM-KISAN', 'Rajasthan', 2024, 6800, 6400, 5900, 15700000, 'pmkisan.gov.in'),
    ('PM-KISAN', 'Bihar', 2024, 5200, 4800, 4200, 11000000, 'pmkisan.gov.in'),
    ('Jal Jeevan', 'Andhra Pradesh', 2024, 1500, 1200, 900, 8000000, 'jaljeevan.gov.in'),
    ('Jal Jeevan', 'Maharashtra', 2024, 1200, 1000, 800, 6500000, 'jaljeevan.gov.in'),
    ('Jal Jeevan', 'Uttar Pradesh', 2024, 2000, 1800, 1200, 9500000, 'jaljeevan.gov.in'),
    ('Jal Jeevan', 'Bihar', 2024, 1000, 800, 400, 4000000, 'jaljeevan.gov.in'),
    ('PM Ujjwala', 'Uttar Pradesh', 2024, 800, 750, 700, 7500000, 'pmujjwala.gov.in'),
    ('PM Ujjwala', 'Bihar', 2024, 650, 600, 550, 6500000, 'pmujjwala.gov.in'),
    ('PM Ujjwala', 'Rajasthan', 2024, 600, 550, 500, 6000000, 'pmujjwala.gov.in'),
]

def load_sample_data():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    print("Loading sample government scheme data...")
    print("=" * 60)
    
    inserted = 0
    skipped = 0
    
    for scheme, state, year, allocated, released, spent, beneficiaries, source in SAMPLE_DATA:
        try:
            c.execute('''INSERT OR REPLACE INTO financials 
                        (scheme_id, state, year, allocated_cr, released_cr, spent_cr, beneficiaries, data_source)
                        VALUES ((SELECT id FROM schemes WHERE name = ?), ?, ?, ?, ?, ?, ?, ?)''',
                    (scheme, state, year, allocated, released, spent, beneficiaries, source))
            inserted += 1
        except Exception as e:
            print(f"⚠️  Error: {str(e)}")
            skipped += 1
    
    conn.commit()
    
    c.execute('SELECT COUNT(*) FROM financials')
    total = c.fetchone()[0]
    conn.close()
    
    print("=" * 60)
    print(f"✅ Inserted: {inserted} records")
    print(f"📊 Total in database: {total} records")
    print("=" * 60)

if __name__ == '__main__':
    load_sample_data()