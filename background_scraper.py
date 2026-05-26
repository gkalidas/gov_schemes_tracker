#!/usr/bin/env python3
"""
Background scraper engine.

Maintains a persistent job queue in SQLite and processes jobs one at a time
in a daemon thread. Starts automatically when Flask starts. On restart, any
job that was mid-run is reset to pending so it retries — nothing is lost.

Job types (in priority order):
  nrega_district  — scrape one NREGA district via DeshSeva
  news_refresh    — refresh Google News cache for one entity
  social_refresh  — refresh Reddit/YouTube cache for one entity
  pmkisan_state   — scrape PM-KISAN beneficiaries for one state (Playwright)
"""

import json
import logging
import sqlite3
import threading
import time

DB_FILE = 'scheme_tracker.db'
logger  = logging.getLogger(__name__)

# Seconds to sleep between successful jobs (keeps requests polite).
JOB_DELAY   = 10
# Extra sleep after a failed job before the next pick-up.
RETRY_DELAY = 90
# Sleep when queue is empty before checking again.
IDLE_SLEEP  = 300

# ── known work to seed ────────────────────────────────────────────────────────

NREGA_STATES = {
    'rajasthan': [
        'ajmer','alwar','banswara','baran','barmer','bharatpur','bhilwara',
        'bikaner','bundi','chittorgarh','churu','dausa','dholpur','dungarpur',
        'hanumangarh','jaipur','jaisalmer','jalore','jhalawar','jhunjhunu',
        'jodhpur','karauli','kota','nagaur','pali','pratapgarh','rajsamand',
        'sawai-madhopur','sikar','sirohi','sri-ganganagar','tonk','udaipur',
    ],
    'bihar': [
        'araria','arwal','aurangabad','banka','begusarai','bhagalpur',
        'bhojpur','buxar','darbhanga','east-champaran','gaya','gopalganj',
        'jamui','jehanabad','kaimur','katihar','khagaria','kishanganj',
        'lakhisarai','madhepura','madhubani','munger','muzaffarpur','nalanda',
        'nawada','patna','purnia','rohtas','saharsa','samastipur','saran',
        'sheikhpura','sheohar','sitamarhi','siwan','supaul','vaishali',
        'west-champaran',
    ],
    'madhya-pradesh': [
        'agar-malwa','alirajpur','anuppur','ashoknagar','balaghat','barwani',
        'betul','bhind','bhopal','burhanpur','chhatarpur','chhindwara',
        'damoh','datia','dewas','dhar','dindori','guna','gwalior','harda',
        'hoshangabad','indore','jabalpur','jhabua','katni','khandwa',
        'khargone','mandla','mandsaur','morena','narsinghpur','neemuch',
        'panna','raisen','rajgarh','ratlam','rewa','sagar','satna',
        'sehore','seoni','shahdol','shajapur','sheopur','shivpuri',
        'sidhi','singrauli','tikamgarh','ujjain','umaria','vidisha',
    ],
    'jharkhand': [
        'bokaro','chatra','deoghar','dhanbad','dumka','east-singhbhum',
        'garhwa','giridih','godda','gumla','hazaribagh','jamtara',
        'khunti','koderma','latehar','lohardaga','pakur','palamu',
        'ramgarh','ranchi','sahebganj','seraikela-kharsawan','simdega',
        'west-singhbhum',
    ],
    'uttar-pradesh': [
        'agra','aligarh','allahabad','ambedkar-nagar','amethi','amroha',
        'auraiya','azamgarh','baghpat','bahraich','ballia','balrampur',
        'banda','barabanki','bareilly','basti','bhadohi','bijnor',
        'budaun','bulandshahr','chandauli','chitrakoot','deoria','etah',
        'etawah','farrukhabad','fatehpur','firozabad','gautam-buddha-nagar',
        'ghaziabad','ghazipur','gonda','gorakhpur','hamirpur','hapur',
        'hardoi','hathras','jalaun','jaunpur','jhansi','kannauj',
        'kanpur-dehat','kanpur-nagar','kasganj','kaushambi','kushinagar',
        'lakhimpur-kheri','lalitpur','lucknow','maharajganj','mahoba',
        'mainpuri','mathura','mau','meerut','mirzapur','moradabad',
        'muzaffarnagar','pilibhit','pratapgarh','rae-bareli','rampur',
        'saharanpur','sambhal','sant-kabir-nagar','shahjahanpur',
        'shamli','shravasti','siddharthnagar','sitapur','sonbhadra',
        'sultanpur','unnao','varanasi',
    ],
}

NEWS_ENTITIES = [
    ('union', 'INDIA',            'NREGA'),
    ('state', 'RAJASTHAN',        'NREGA'),
    ('state', 'BIHAR',            'NREGA'),
    ('state', 'UTTAR PRADESH',    'NREGA'),
    ('state', 'MADHYA PRADESH',   'NREGA'),
    ('state', 'JHARKHAND',        'NREGA'),
]

PMKISAN_STATES = [
    'RAJASTHAN', 'BIHAR', 'UTTAR PRADESH', 'MADHYA PRADESH', 'JHARKHAND',
    'ODISHA', 'WEST BENGAL', 'ANDHRA PRADESH', 'TELANGANA', 'KARNATAKA',
]

# ── queue table ───────────────────────────────────────────────────────────────

def init_queue():
    conn = sqlite3.connect(DB_FILE)
    c    = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scraper_queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_type    TEXT    NOT NULL,
        params      TEXT    NOT NULL,
        status      TEXT    DEFAULT 'pending',
        priority    INTEGER DEFAULT 5,
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        last_error  TEXT,
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(job_type, params)
    )''')
    # Any job stuck as 'running' from a previous crash gets retried.
    c.execute(
        "UPDATE scraper_queue SET status='pending', updated_at=CURRENT_TIMESTAMP "
        "WHERE status='running'"
    )
    conn.commit()
    conn.close()


def seed_jobs():
    """Idempotently insert all known jobs. Already-queued jobs are untouched."""
    conn = sqlite3.connect(DB_FILE)
    c    = conn.cursor()

    def enqueue(job_type, params_dict, priority):
        params_str = json.dumps(params_dict, sort_keys=True)
        c.execute(
            'INSERT OR IGNORE INTO scraper_queue (job_type, params, priority) VALUES (?,?,?)',
            (job_type, params_str, priority),
        )

    for state_slug, districts in NREGA_STATES.items():
        for district in districts:
            enqueue('nrega_district', {'district': district, 'state_slug': state_slug}, 1)

    for level, entity, scheme in NEWS_ENTITIES:
        enqueue('news_refresh',   {'entity': entity, 'level': level, 'scheme': scheme}, 2)
        enqueue('social_refresh', {'entity': entity, 'level': level, 'scheme': scheme}, 3)

    for state in PMKISAN_STATES:
        enqueue('pmkisan_state', {'state': state}, 4)

    conn.commit()
    conn.close()
    logger.info('[scraper] Queue seeded.')


# ── job runners ───────────────────────────────────────────────────────────────

def _run_nrega_district(params):
    import scrape_real_data as srd
    data = srd.scrape_district_for_state(params['state_slug'], params['district'])
    if not data:
        raise RuntimeError(f"No data returned for {params['state_slug']}/{params['district']}")
    srd.save_district_data(data)


def _run_news_refresh(params):
    import fetch_news as fn
    fn.init_news_table()
    if params['level'] == 'district':
        fn.fetch_for_district(params['entity'], params.get('scheme', 'NREGA'))
    else:
        fn.fetch_for_state(params['entity'], params.get('scheme', 'NREGA'))


def _run_social_refresh(params):
    import fetch_social as fs
    fs.init_social_table()
    if params['level'] == 'district':
        fs.run(district=params['entity'], scheme=params.get('scheme', 'NREGA'), workers=1)
    else:
        fs.run(state=params['entity'], scheme=params.get('scheme', 'NREGA'), workers=1)


def _run_pmkisan_state(params):
    try:
        import scrape_pmkisan as sp
    except ImportError:
        raise RuntimeError('playwright not installed — run: playwright install chromium')
    sp.init_table()
    sp.scrape(target_state=params['state'], resume=True, workers=1)


_RUNNERS = {
    'nrega_district':  _run_nrega_district,
    'news_refresh':    _run_news_refresh,
    'social_refresh':  _run_social_refresh,
    'pmkisan_state':   _run_pmkisan_state,
}

# ── engine ────────────────────────────────────────────────────────────────────

class BackgroundScraper(threading.Thread):
    def __init__(self, startup_delay=120):
        super().__init__(daemon=True, name='background-scraper')
        self._stop          = threading.Event()
        self._startup_delay = startup_delay

    def run(self):
        if self._startup_delay > 0:
            logger.info('[scraper] Waiting %ds before first job.', self._startup_delay)
            self._stop.wait(self._startup_delay)
        logger.info('[scraper] Started.')
        while not self._stop.is_set():
            job = self._claim_next()
            if job is None:
                logger.info('[scraper] Queue empty — sleeping %ds.', IDLE_SLEEP)
                self._stop.wait(IDLE_SLEEP)
                continue

            job_id, job_type, params_str = job
            params = json.loads(params_str)
            logger.info('[scraper] Job #%d  %s  %s', job_id, job_type, params_str)

            try:
                runner = _RUNNERS.get(job_type)
                if runner is None:
                    raise ValueError(f'Unknown job_type: {job_type}')
                runner(params)
                self._mark(job_id, 'done')
                logger.info('[scraper] Done  #%d', job_id)
            except Exception as exc:
                logger.warning('[scraper] Failed #%d: %s', job_id, exc)
                self._handle_failure(job_id, str(exc))

            self._stop.wait(JOB_DELAY)

    def _claim_next(self):
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute(
            "SELECT id, job_type, params FROM scraper_queue "
            "WHERE status='pending' ORDER BY priority ASC, id ASC LIMIT 1"
        )
        row = c.fetchone()
        if row:
            c.execute(
                "UPDATE scraper_queue SET status='running', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row[0],),
            )
            conn.commit()
        conn.close()
        return row

    def _mark(self, job_id, status):
        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "UPDATE scraper_queue SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (status, job_id),
        )
        conn.commit()
        conn.close()

    def _handle_failure(self, job_id, error):
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute('SELECT retry_count, max_retries FROM scraper_queue WHERE id=?', (job_id,))
        retry_count, max_retries = c.fetchone()
        new_count = retry_count + 1
        if new_count <= max_retries:
            c.execute(
                "UPDATE scraper_queue SET status='pending', retry_count=?, last_error=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_count, error, job_id),
            )
            logger.info('[scraper] Job #%d will retry (%d/%d).', job_id, new_count, max_retries)
        else:
            c.execute(
                "UPDATE scraper_queue SET status='failed', last_error=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (error, job_id),
            )
            logger.warning('[scraper] Job #%d permanently failed.', job_id)
        conn.commit()
        conn.close()
        self._stop.wait(RETRY_DELAY)


# ── public API ────────────────────────────────────────────────────────────────

_instance = None

def start(db_file=None, startup_delay=120):
    global _instance, DB_FILE
    if db_file:
        DB_FILE = db_file
    init_queue()
    seed_jobs()
    _instance = BackgroundScraper(startup_delay=startup_delay)
    _instance.start()
    logger.info('[scraper] Background scraper running (first job in %ds).', startup_delay)
    return _instance


def queue_status():
    """Return a summary dict suitable for the /api/scraper/status endpoint."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT status, job_type, COUNT(*) as n FROM scraper_queue "
        "GROUP BY status, job_type ORDER BY status, job_type"
    )
    rows = c.fetchall()

    c.execute("SELECT id, job_type, params, updated_at FROM scraper_queue WHERE status='running' LIMIT 1")
    running_row = c.fetchone()

    c.execute("SELECT id, job_type, params, last_error, updated_at FROM scraper_queue "
              "WHERE status='failed' ORDER BY updated_at DESC LIMIT 10")
    recent_failed = [dict(r) for r in c.fetchall()]
    conn.close()

    totals   = {'pending': 0, 'running': 0, 'done': 0, 'failed': 0}
    by_type  = {}
    for row in rows:
        totals[row['status']]  = totals.get(row['status'], 0) + row['n']
        by_type.setdefault(row['job_type'], {})
        by_type[row['job_type']][row['status']] = row['n']

    return {
        'totals':         totals,
        'by_type':        by_type,
        'current_job':    dict(running_row) if running_row else None,
        'recent_failed':  recent_failed,
    }
