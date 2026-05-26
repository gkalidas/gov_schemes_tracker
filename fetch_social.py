"""
Fetch and cache social media posts for scheme + district/state combos.

Platforms supported:
  Reddit  — free, no API key needed (uses public JSON endpoint)
  YouTube — free (10k units/day), requires a Google API key

Instagram — Meta Graph API requires business account + app approval; not supported.

Run:
  python3 fetch_social.py                             # Reddit only, all districts
  python3 fetch_social.py --district UDAIPUR          # Reddit, one district
  python3 fetch_social.py --youtube --key YOUR_KEY    # enable YouTube too
  python3 fetch_social.py --district UDAIPUR --youtube --key YOUR_KEY
"""

import sqlite3
import urllib.request
import urllib.parse
import json
import time
import argparse
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

_db_lock    = threading.Lock()
_print_lock = threading.Lock()

def _print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

from config import DB_FILE, REDDIT_SUBREDDITS, YOUTUBE_API_KEY
YOUTUBE_SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'

RAJASTHAN_DISTRICTS = [
    'AJMER', 'ALWAR', 'BANSWARA', 'BARAN', 'BARMER', 'BHARATPUR', 'BHILWARA',
    'BIKANER', 'BUNDI', 'CHITTORGARH', 'CHURU', 'DAUSA', 'DHOLPUR', 'DUNGARPUR',
    'HANUMANGARH', 'JAIPUR', 'JAISALMER', 'JALORE', 'JHALAWAR', 'JHUNJHUNU',
    'JODHPUR', 'KARAULI', 'KOTA', 'NAGAUR', 'PALI', 'PRATAPGARH', 'RAJSAMAND',
    'SAWAI MADHOPUR', 'SIKAR', 'SIROHI', 'SRI GANGANAGAR', 'TONK', 'UDAIPUR',
]


# ─── DB ───────────────────────────────────────────────────────────────────────

def init_social_table():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS social_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        scheme TEXT NOT NULL,
        level TEXT NOT NULL,
        entity_name TEXT NOT NULL,
        title TEXT,
        url TEXT UNIQUE,
        author TEXT,
        score INTEGER DEFAULT 0,
        comments INTEGER DEFAULT 0,
        thumbnail_url TEXT,
        published_at TEXT,
        snippet TEXT,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_social_entity ON social_cache(scheme, level, entity_name)')
    conn.commit()
    conn.close()
    print('social_cache table ready.')


def save_posts(posts):
    if not posts:
        return 0
    with _db_lock:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        saved = 0
        for p in posts:
            try:
                c.execute('''INSERT OR REPLACE INTO social_cache
                    (platform, scheme, level, entity_name, title, url,
                     author, score, comments, thumbnail_url, published_at, snippet)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (p['platform'], p['scheme'], p['level'], p['entity_name'],
                     p['title'], p['url'], p['author'], p.get('score', 0),
                     p.get('comments', 0), p.get('thumbnail_url', ''),
                     p.get('published_at', ''), p.get('snippet', '')))
                saved += 1
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
    return saved


# ─── REDDIT ───────────────────────────────────────────────────────────────────

def fetch_reddit(query, limit=10, retries=4):
    encoded = urllib.parse.quote_plus(query)
    url = (f'https://www.reddit.com/search.json'
           f'?q={encoded}&sort=relevance&limit={limit}&type=link&t=year')
    headers = {'User-Agent': 'GovSchemeTracker/1.0 (transparency research)'}
    delay = 5
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            return data.get('data', {}).get('children', [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                _print(f'  Reddit 429 — backing off {delay}s (attempt {attempt+1}/{retries})')
                time.sleep(delay)
                delay *= 2
            else:
                _print(f'  Reddit fetch failed: {e}')
                return []
        except Exception as e:
            _print(f'  Reddit fetch failed: {e}')
            return []
    _print(f'  Reddit gave up after {retries} retries for: {query[:60]}')
    return []


def reddit_posts_for(entity, scheme, level):
    scheme_term = 'MGNREGA' if scheme == 'NREGA' else scheme
    queries = [
        f'{scheme_term} {entity} corruption fraud',
        f'{scheme_term} {entity} Rajasthan',
    ]
    posts = []
    seen_urls = set()
    for q in queries:
        children = fetch_reddit(q)
        for child in children:
            d = child.get('data', {})
            url = d.get('url', '')
            permalink = 'https://reddit.com' + d.get('permalink', '')
            # use permalink (reddit thread) as the canonical URL
            if permalink in seen_urls:
                continue
            seen_urls.add(permalink)

            title = d.get('title', '').strip()
            if not title:
                continue

            created = d.get('created_utc', 0)
            pub = datetime.fromtimestamp(created, tz=timezone.utc).strftime('%a, %d %b %Y %H:%M:%S +0000') if created else ''

            posts.append({
                'platform': 'reddit',
                'scheme': scheme,
                'level': level,
                'entity_name': entity,
                'title': title,
                'url': permalink,
                'author': 'u/' + d.get('author', ''),
                'score': d.get('score', 0),
                'comments': d.get('num_comments', 0),
                'thumbnail_url': d.get('thumbnail', '') if d.get('thumbnail', '').startswith('http') else '',
                'published_at': pub,
                'snippet': d.get('selftext', '')[:300] or d.get('url', ''),
            })
        time.sleep(0.3)   # reduced: parallel workers spread the load
    return posts


# ─── YOUTUBE ──────────────────────────────────────────────────────────────────

def fetch_youtube(query, api_key, max_results=5):
    params = urllib.parse.urlencode({
        'part': 'snippet',
        'q': query,
        'type': 'video',
        'regionCode': 'IN',
        'relevanceLanguage': 'en',
        'maxResults': max_results,
        'key': api_key,
    })
    url = f'{YOUTUBE_SEARCH_URL}?{params}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GovSchemeTracker/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read()).get('items', [])
    except Exception as e:
        print(f'  YouTube fetch failed: {e}')
        return []


def youtube_posts_for(entity, scheme, level, api_key):
    scheme_term = 'MGNREGA' if scheme == 'NREGA' else scheme
    queries = [
        f'{scheme_term} {entity} Rajasthan corruption',
        f'{scheme_term} {entity} Rajasthan',
    ]
    posts = []
    seen = set()
    for q in queries:
        items = fetch_youtube(q, api_key)
        for item in items:
            vid_id = item.get('id', {}).get('videoId', '')
            if not vid_id or vid_id in seen:
                continue
            seen.add(vid_id)
            snip = item.get('snippet', {})
            pub_raw = snip.get('publishedAt', '')
            try:
                pub = datetime.fromisoformat(pub_raw.replace('Z', '+00:00')).strftime('%a, %d %b %Y %H:%M:%S +0000')
            except Exception:
                pub = pub_raw
            thumb = snip.get('thumbnails', {}).get('default', {}).get('url', '')
            posts.append({
                'platform': 'youtube',
                'scheme': scheme,
                'level': level,
                'entity_name': entity,
                'title': snip.get('title', '').strip(),
                'url': f'https://www.youtube.com/watch?v={vid_id}',
                'author': snip.get('channelTitle', ''),
                'score': 0,
                'comments': 0,
                'thumbnail_url': thumb,
                'published_at': pub,
                'snippet': snip.get('description', '')[:300],
            })
        time.sleep(0.3)
    return posts


# ─── RUNNER ───────────────────────────────────────────────────────────────────

def _fetch_entity(level, entity, scheme, youtube_key):
    """Fetch Reddit + YouTube for one entity. Returns (entity, total_saved)."""
    total = 0
    posts = reddit_posts_for(entity, scheme, level)
    total += save_posts(posts)
    if youtube_key:
        yt = youtube_posts_for(entity, scheme, level, youtube_key)
        total += save_posts(yt)
    return entity, total


def run(district=None, state=None, scheme='NREGA', youtube_key=None, workers=3):
    init_social_table()
    if district:
        targets = [('district', district.upper())]
    elif state:
        targets = [('state', state.upper())]
    else:
        targets = [('state', 'RAJASTHAN')] + [('district', d) for d in RAJASTHAN_DISTRICTS]

    if len(targets) == 1:
        # Single target — run directly, no threading overhead
        level, entity = targets[0]
        entity, n = _fetch_entity(level, entity, scheme, youtube_key)
        print(f'{entity}: {n} saved')
        return

    total_count = len(targets)
    done = 0
    grand = 0
    counter_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_fetch_entity, level, entity, scheme, youtube_key): (level, entity)
            for level, entity in targets
        }
        for future in as_completed(futures):
            try:
                entity, n = future.result()
            except Exception as e:
                _, entity = futures[future]
                _print(f'  ERROR {entity}: {e}')
                n = 0
            with counter_lock:
                done  += 1
                grand += n
                _print(f'  [{done}/{total_count}] {entity}: {n} saved (total: {grand})')

    print(f'\nDone. Total new posts saved: {grand}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--district', help='Single district (e.g. UDAIPUR)')
    parser.add_argument('--state',    help='State-level fetch (e.g. RAJASTHAN)')
    parser.add_argument('--scheme',   default='NREGA')
    parser.add_argument('--youtube',  action='store_true', help='Enable YouTube search')
    parser.add_argument('--key',      help='Google API key (required for --youtube)')
    parser.add_argument('--workers',  type=int, default=2,
                        help='Parallel workers (default 2, Reddit rate limit is ~60 req/min)')
    args = parser.parse_args()

    if args.youtube and not args.key:
        print('Error: --youtube requires --key YOUR_GOOGLE_API_KEY')
        print('Get a free key at: https://console.cloud.google.com → APIs → YouTube Data API v3')
        exit(1)

    import time as _time
    t0 = _time.time()
    yt_key = args.key if args.youtube else None
    run(
        district=args.district,
        state=args.state,
        scheme=args.scheme,
        youtube_key=yt_key,
        workers=args.workers,
    )
    print(f'Elapsed: {_time.time() - t0:.0f}s')
