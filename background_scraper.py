#!/usr/bin/env python3
"""
Background scraper engine.

Maintains a persistent job queue in SQLite and processes jobs in a daemon
thread. Starts automatically when Flask starts. On restart, any job that was
mid-run is reset to pending so it retries — nothing is lost.

Per-domain rate limiting: tracks the last time each domain was hit and skips
jobs whose domain is still in cooldown, picking the next eligible job instead.
This lets different-domain jobs run back-to-back without wasted idle time.
"""

import json
import logging
import sqlite3
import time

import config
import constants
import states

logger = logging.getLogger(__name__)

# ── queue table ───────────────────────────────────────────────────────────────

def init_queue():
    conn = sqlite3.connect(config.DB_FILE)
    c    = conn.cursor()
    c.execute(f'''CREATE TABLE IF NOT EXISTS scraper_queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        job_type    TEXT    NOT NULL,
        params      TEXT    NOT NULL,
        status      TEXT    DEFAULT '{constants.STATUS_PENDING}',
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
        f"UPDATE scraper_queue SET status='{constants.STATUS_PENDING}', "
        f"updated_at=CURRENT_TIMESTAMP WHERE status='{constants.STATUS_RUNNING}'"
    )
    conn.commit()
    conn.close()


def seed_jobs():
    """Idempotently insert all known jobs. Already-queued jobs are untouched."""
    conn = sqlite3.connect(config.DB_FILE)
    c    = conn.cursor()

    def enqueue(job_type, params_dict, priority):
        params_str = json.dumps(params_dict, sort_keys=True)
        c.execute(
            'INSERT OR IGNORE INTO scraper_queue (job_type, params, priority) VALUES (?,?,?)',
            (job_type, params_str, priority),
        )

    for state_slug, districts in states.NREGA_STATES.items():
        for district in districts:
            enqueue(constants.JOB_NREGA_DISTRICT,
                    {'district': district, 'state_slug': state_slug}, 1)

    for level, entity, scheme in states.NEWS_ENTITIES:
        enqueue(constants.JOB_NEWS_REFRESH,
                {'entity': entity, 'level': level, 'scheme': scheme}, 2)
        enqueue(constants.JOB_SOCIAL_REFRESH,
                {'entity': entity, 'level': level, 'scheme': scheme}, 3)

    for state in states.PMKISAN_STATES:
        enqueue(constants.JOB_PMKISAN_STATE, {'state': state}, 4)

    conn.commit()
    conn.close()
    logger.info('[scraper] Queue seeded.')


# ── job runners ───────────────────────────────────────────────────────────────

def _run_nrega_district(params):
    import scrape_real_data as srd
    data = srd.scrape_district_for_state(params['state_slug'], params['district'])
    if not data:
        raise RuntimeError(f"No data for {params['state_slug']}/{params['district']}")
    srd.save_district_data(data)


def _run_news_refresh(params):
    import fetch_news as fn
    fn.init_news_table()
    if params['level'] == 'district':
        fn.fetch_for_district(params['entity'], params.get('scheme', constants.SCHEME_NREGA))
    else:
        fn.fetch_for_state(params['entity'], params.get('scheme', constants.SCHEME_NREGA))


def _run_social_refresh(params):
    import fetch_social as fs
    fs.init_social_table()
    if params['level'] == 'district':
        fs.run(district=params['entity'],
               scheme=params.get('scheme', constants.SCHEME_NREGA), workers=1)
    else:
        fs.run(state=params['entity'],
               scheme=params.get('scheme', constants.SCHEME_NREGA), workers=1)


def _run_pmkisan_state(params):
    try:
        import scrape_pmkisan as sp
    except ImportError:
        raise RuntimeError('playwright not installed — run: playwright install chromium')
    sp.init_table()
    sp.scrape(target_state=params['state'], resume=True, workers=1)


_RUNNERS = {
    constants.JOB_NREGA_DISTRICT: _run_nrega_district,
    constants.JOB_NEWS_REFRESH:   _run_news_refresh,
    constants.JOB_SOCIAL_REFRESH: _run_social_refresh,
    constants.JOB_PMKISAN_STATE:  _run_pmkisan_state,
}

# ── engine ────────────────────────────────────────────────────────────────────

import threading

class BackgroundScraper(threading.Thread):
    def __init__(self, startup_delay=None):
        super().__init__(daemon=True, name='background-scraper')
        self._stop         = threading.Event()
        self._startup_delay = startup_delay if startup_delay is not None \
                              else config.SCRAPER_STARTUP_DELAY
        # domain → timestamp of last request (in-memory; resets on restart, that's fine)
        self._last_hit: dict = {}

    def run(self):
        if self._startup_delay > 0:
            logger.info('[scraper] Waiting %ds before first job.', self._startup_delay)
            self._stop.wait(self._startup_delay)
        logger.info('[scraper] Started.')
        while not self._stop.is_set():
            job = self._claim_next()
            if job is None:
                logger.info('[scraper] Queue empty — sleeping %ds.', config.SCRAPER_IDLE_SLEEP)
                self._stop.wait(config.SCRAPER_IDLE_SLEEP)
                continue

            job_id, job_type, params_str = job
            params = json.loads(params_str)
            logger.info('[scraper] Job #%d  %s  %s', job_id, job_type, params_str)

            domain = constants.JOB_DOMAIN.get(job_type, 'unknown')
            try:
                runner = _RUNNERS.get(job_type)
                if runner is None:
                    raise ValueError(f'Unknown job_type: {job_type}')
                runner(params)
                self._last_hit[domain] = time.monotonic()
                self._mark(job_id, constants.STATUS_DONE)
                logger.info('[scraper] Done  #%d', job_id)
            except Exception as exc:
                self._last_hit[domain] = time.monotonic()
                logger.warning('[scraper] Failed #%d: %s', job_id, exc)
                self._handle_failure(job_id, str(exc))

    def _claim_next(self):
        """
        Find the highest-priority pending job whose domain is not in cooldown.
        If every pending job is in cooldown, sleep until the soonest one clears.
        """
        conn = sqlite3.connect(config.DB_FILE)
        c    = conn.cursor()
        c.execute(
            f"SELECT id, job_type, params FROM scraper_queue "
            f"WHERE status='{constants.STATUS_PENDING}' ORDER BY priority ASC, id ASC"
        )
        candidates = c.fetchall()

        now = time.monotonic()
        chosen    = None
        min_wait  = None

        for row in candidates:
            job_id, job_type, params_str = row
            domain     = constants.JOB_DOMAIN.get(job_type, 'unknown')
            cooldown   = config.DOMAIN_DELAYS.get(domain, 0)
            elapsed    = now - self._last_hit.get(domain, 0)
            remaining  = cooldown - elapsed

            if remaining <= 0:
                chosen = row
                break
            if min_wait is None or remaining < min_wait:
                min_wait = remaining

        if chosen:
            c.execute(
                f"UPDATE scraper_queue SET status='{constants.STATUS_RUNNING}', "
                f"updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (chosen[0],),
            )
            conn.commit()
            conn.close()
            return chosen

        conn.close()

        if min_wait is not None:
            logger.debug('[scraper] All domains in cooldown — sleeping %.1fs.', min_wait)
            self._stop.wait(min_wait)
        return None

    def _mark(self, job_id, status):
        conn = sqlite3.connect(config.DB_FILE)
        conn.execute(
            'UPDATE scraper_queue SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (status, job_id),
        )
        conn.commit()
        conn.close()

    def _handle_failure(self, job_id, error):
        conn = sqlite3.connect(config.DB_FILE)
        c    = conn.cursor()
        c.execute('SELECT retry_count, max_retries FROM scraper_queue WHERE id=?', (job_id,))
        retry_count, max_retries = c.fetchone()
        new_count = retry_count + 1
        if new_count <= max_retries:
            c.execute(
                f"UPDATE scraper_queue SET status='{constants.STATUS_PENDING}', "
                f"retry_count=?, last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_count, error, job_id),
            )
            logger.info('[scraper] Job #%d will retry (%d/%d).', job_id, new_count, max_retries)
        else:
            c.execute(
                f"UPDATE scraper_queue SET status='{constants.STATUS_FAILED}', "
                f"last_error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (error, job_id),
            )
            logger.warning('[scraper] Job #%d permanently failed.', job_id)
        conn.commit()
        conn.close()
        self._stop.wait(config.SCRAPER_RETRY_DELAY)


# ── public API ────────────────────────────────────────────────────────────────

_instance = None

def start(db_file=None, startup_delay=None):
    global _instance
    if db_file:
        config.DB_FILE = db_file
    init_queue()
    seed_jobs()
    _instance = BackgroundScraper(startup_delay=startup_delay)
    _instance.start()
    logger.info('[scraper] Background scraper running.')
    return _instance


def queue_status():
    """Return a summary dict for the /api/scraper/status endpoint."""
    conn = sqlite3.connect(config.DB_FILE)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute(
        'SELECT status, job_type, COUNT(*) as n FROM scraper_queue '
        'GROUP BY status, job_type ORDER BY status, job_type'
    )
    rows = c.fetchall()

    c.execute(
        f"SELECT id, job_type, params, updated_at FROM scraper_queue "
        f"WHERE status='{constants.STATUS_RUNNING}' LIMIT 1"
    )
    running_row = c.fetchone()

    c.execute(
        f"SELECT id, job_type, params, last_error, updated_at FROM scraper_queue "
        f"WHERE status='{constants.STATUS_FAILED}' ORDER BY updated_at DESC LIMIT 10"
    )
    recent_failed = [dict(r) for r in c.fetchall()]
    conn.close()

    totals  = {s: 0 for s in (constants.STATUS_PENDING, constants.STATUS_RUNNING,
                               constants.STATUS_DONE, constants.STATUS_FAILED)}
    by_type = {}
    for row in rows:
        totals[row['status']] = totals.get(row['status'], 0) + row['n']
        by_type.setdefault(row['job_type'], {})
        by_type[row['job_type']][row['status']] = row['n']

    return {
        'totals':        totals,
        'by_type':       by_type,
        'current_job':   dict(running_row) if running_row else None,
        'recent_failed': recent_failed,
    }
