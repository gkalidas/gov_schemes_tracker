"""
Central configuration. All tuneable values live here.
Other files import from this module — never define DB_FILE or timing
constants elsewhere.

Environment variable overrides (useful for deployment):
  DB_FILE              path to SQLite database
  PORT                 Flask port
  YOUTUBE_API_KEY      Google Data API v3 key (optional — YouTube skipped if empty)
  DATA_GOV_API_KEY     data.gov.in API key — get one free at https://data.gov.in/user/register
                       Required for official NREGA data + cross-verification.
                       Without it, cross-verification jobs are skipped gracefully.
"""
import os

# ── database ──────────────────────────────────────────────────────────────────

DB_FILE = os.getenv('DB_FILE', 'scheme_tracker.db')

# ── server ────────────────────────────────────────────────────────────────────

PORT = int(os.getenv('PORT', 5000))

# ── api keys ──────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY  = os.getenv('YOUTUBE_API_KEY',  '')
DATA_GOV_API_KEY = os.getenv('DATA_GOV_API_KEY', '')

# ── social fetcher ────────────────────────────────────────────────────────────

REDDIT_SUBREDDITS = ['india', 'IndianPolitics', 'indianews', 'MGNREGA', 'Rajasthan']

# ── background scraper timing (seconds) ──────────────────────────────────────

# How long after app start before the first job runs.
SCRAPER_STARTUP_DELAY = 120

# How long to sleep when the queue is empty before checking again.
SCRAPER_IDLE_SLEEP = 300

# Extra sleep after a failed job before picking up the next one.
SCRAPER_RETRY_DELAY = 90

# Minimum gap between consecutive requests to the same domain.
# Add an entry here whenever a new data source is added.
DOMAIN_DELAYS = {
    'deshseva.in':     8,
    'news.google.com': 5,
    'reddit.com':      15,
    'pmkisan.gov.in':  10,
    'api.data.gov.in': 3,
}

# Tolerance for cross-verification: differences within this % are ignored.
VERIFY_TOLERANCE_PCT = 5.0
