"""
Fetch and cache news articles for scheme + district/state combos via Google News RSS.

No API key required. Uses standard library only (urllib, xml.etree).

Run:
  python3 fetch_news.py                        # all 33 Rajasthan districts
  python3 fetch_news.py --district UDAIPUR     # single district
  python3 fetch_news.py --state RAJASTHAN      # state-level only
  python3 fetch_news.py --scheme PM-KISAN      # different scheme
"""

import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
import time
import argparse
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus

_db_lock    = threading.Lock()
_print_lock = threading.Lock()

def _print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

from config import DB_FILE

NATIONAL_DOMAINS = {
    'thehindu.com', 'timesofindia.com', 'ndtv.com', 'indianexpress.com',
    'hindustantimes.com', 'thewire.in', 'scroll.in', 'livemint.com',
    'economictimes.com', 'businessstandard.com', 'theprint.in',
    'firstpost.com', 'news18.com', 'thequint.com', 'newslaundry.com',
    'telegraphindia.com', 'deccanherald.com', 'thestatesman.com',
}
LOCAL_DOMAINS = {
    'bhaskar.com', 'patrika.com', 'rajasthanpatrika.com',
    'jagran.com', 'amarujala.com', 'punjabkesari.com',
    'navbharattimes.com', 'lokmat.com', 'livehindustan.com',
    'rajexpress.in', 'rajasthandarpan.in',
}
OFFICIAL_DOMAINS_SUFFIX = ('.nic.in', '.gov.in')


def classify_domain(url):
    m = re.search(r'https?://(?:www\.)?([^/?#]+)', url)
    if not m:
        return 'other'
    domain = m.group(1).lower()
    if any(domain.endswith(s) for s in OFFICIAL_DOMAINS_SUFFIX):
        return 'official'
    if any(d in domain for d in NATIONAL_DOMAINS):
        return 'national_news'
    if any(d in domain for d in LOCAL_DOMAINS):
        return 'local_news'
    return 'national_news'  # fallback for unknown news sources


def fetch_rss(query):
    encoded = quote_plus(query)
    url = f'https://news.google.com/rss/search?q={encoded}&hl=en-IN&gl=IN&ceid=IN:en'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as e:
        print(f'  RSS fetch failed: {e}')
        return None


def parse_articles(xml_bytes, scheme, level, entity_name, query):
    if not xml_bytes:
        return []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f'  XML parse error: {e}')
        return []

    articles = []
    for item in root.findall('.//item'):
        title = (item.findtext('title') or '').strip()
        link  = (item.findtext('link') or '').strip()
        pub   = (item.findtext('pubDate') or '').strip()
        desc  = (item.findtext('description') or '').strip()

        snippet = re.sub(r'<[^>]+>', '', desc)[:300]

        if not title or not link:
            continue

        # Google News titles end with " - Source Name"; extract source
        source_name = ''
        if ' - ' in title:
            source_name = title.rsplit(' - ', 1)[-1].strip()
            clean_title = title.rsplit(' - ', 1)[0].strip()
        else:
            clean_title = title

        source_type = classify_domain(link)

        articles.append({
            'scheme': scheme,
            'level': level,
            'entity_name': entity_name,
            'title': clean_title,
            'url': link,
            'source_name': source_name,
            'source_type': source_type,
            'published_at': pub,
            'snippet': snippet,
            'query_used': query,
        })
    return articles


SCHEME_KEYWORDS = {
    'NREGA':    {'nrega', 'mgnrega', 'mahatma', 'job card', 'muster', 'wage', 'worker',
                 'rozgar', 'labour', 'labor', 'funds', 'allocation', 'expenditure',
                 'scheme', 'corruption', 'fraud', 'scam', 'misuse', 'sarpanch'},
    'PM-KISAN': {'pm-kisan', 'pmkisan', 'kisan', 'farmer', 'kisaan', 'instalment',
                 'installment', 'beneficiary', 'agriculture', 'crop'},
    'PM-JAY':   {'pm-jay', 'pmjay', 'ayushman', 'health', 'hospital', 'insurance',
                 'medical', 'treatment', 'beneficiary'},
}
_DEFAULT_KEYWORDS = {'scheme', 'funds', 'corruption', 'fraud', 'scam', 'misuse',
                     'allocation', 'expenditure', 'beneficiary', 'government'}


def _is_relevant(article):
    """Return True if title or snippet contains at least one scheme-related keyword."""
    keywords = SCHEME_KEYWORDS.get(article['scheme'], _DEFAULT_KEYWORDS)
    haystack = (article['title'] + ' ' + article['snippet']).lower()
    return any(kw in haystack for kw in keywords)


def save_articles(articles):
    if not articles:
        return 0
    with _db_lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        saved = 0
        for a in articles:
            if not _is_relevant(a):
                continue
            try:
                c.execute('''INSERT OR REPLACE INTO news_cache
                    (scheme, level, entity_name, title, url, source_name, source_type,
                     published_at, snippet, query_used, fetched_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)''',
                    (a['scheme'], a['level'], a['entity_name'], a['title'], a['url'],
                     a['source_name'], a['source_type'], a['published_at'],
                     a['snippet'], a['query_used']))
                saved += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
    return saved


def fetch_for_district(district, scheme='NREGA'):
    scheme_term = 'MGNREGA' if scheme == 'NREGA' else scheme
    queries = [
        f'{scheme_term} {district} Rajasthan corruption fraud misuse',
        f'{scheme_term} {district} Rajasthan',
        f'NREGA {district} Rajasthan money scam',
    ]
    total = 0
    for q in queries:
        xml = fetch_rss(q)
        articles = parse_articles(xml, scheme, 'district', district, q)
        total += save_articles(articles)
        time.sleep(0.4)   # reduced: parallel workers spread the load
    return total


def fetch_for_state(state='RAJASTHAN', scheme='NREGA'):
    scheme_term = 'MGNREGA' if scheme == 'NREGA' else scheme
    queries = [
        f'{scheme_term} {state} corruption fraud 2025',
        f'{scheme_term} {state} misuse funds',
        f'{scheme_term} {state}',
    ]
    total = 0
    for q in queries:
        xml = fetch_rss(q)
        articles = parse_articles(xml, scheme, 'state', state, q)
        total += save_articles(articles)
        time.sleep(0.4)
    return total


def _run_districts_parallel(districts, scheme, workers):
    """Fetch all districts concurrently and print live progress."""
    total = len(districts)
    done  = 0
    grand = 0
    lock  = threading.Lock()

    def task(district):
        return district, fetch_for_district(district, scheme)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(task, d): d for d in districts}
        for future in as_completed(futures):
            try:
                district, n = future.result()
            except Exception as e:
                district = futures[future]
                _print(f'  ERROR {district}: {e}')
                n = 0
            with lock:
                done  += 1
                grand += n
                _print(f'  [{done}/{total}] {district}: {n} new articles (running total: {grand})')

    return grand


def init_news_table():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
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
    conn.commit()
    conn.close()
    print('news_cache table ready.')


# All 33 Rajasthan district names (matches fund_flow entity_name)
RAJASTHAN_DISTRICTS = [
    'AJMER', 'ALWAR', 'BANSWARA', 'BARAN', 'BARMER', 'BHARATPUR', 'BHILWARA',
    'BIKANER', 'BUNDI', 'CHITTORGARH', 'CHURU', 'DAUSA', 'DHOLPUR', 'DUNGARPUR',
    'HANUMANGARH', 'JAIPUR', 'JAISALMER', 'JALORE', 'JHALAWAR', 'JHUNJHUNU',
    'JODHPUR', 'KARAULI', 'KOTA', 'NAGAUR', 'PALI', 'PRATAPGARH', 'RAJSAMAND',
    'SAWAI MADHOPUR', 'SIKAR', 'SIROHI', 'SRI GANGANAGAR', 'TONK', 'UDAIPUR',
]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--district', help='Single district (e.g. UDAIPUR)')
    parser.add_argument('--state',    help='State-level only (e.g. RAJASTHAN)')
    parser.add_argument('--scheme',   default='NREGA')
    parser.add_argument('--workers',  type=int, default=5,
                        help='Parallel workers (default 5, lower if rate-limited)')
    args = parser.parse_args()

    init_news_table()

    if args.district:
        d = args.district.upper()
        print(f'Fetching news for district: {d}')
        n = fetch_for_district(d, args.scheme)
        print(f'Saved: {n}')

    elif args.state:
        s = args.state.upper()
        print(f'Fetching news for state: {s}')
        n = fetch_for_state(s, args.scheme)
        print(f'Saved: {n}')

    else:
        import time as _time
        t0 = _time.time()
        print(f'Fetching news for RAJASTHAN (state) + {len(RAJASTHAN_DISTRICTS)} districts '
              f'with {args.workers} workers...\n')

        # State-level first (single fetch, not parallelised)
        state_n = fetch_for_state('RAJASTHAN', args.scheme)
        print(f'State-level: {state_n} saved\n')

        district_n = _run_districts_parallel(RAJASTHAN_DISTRICTS, args.scheme, args.workers)
        elapsed = _time.time() - t0
        print(f'\nDone in {elapsed:.0f}s. Total saved: {state_n + district_n}')
