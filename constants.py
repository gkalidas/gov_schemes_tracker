"""
Shared string constants. Import these instead of spelling strings inline so
a typo silently produces the wrong behaviour (e.g. a job that never runs
because its type doesn't match any runner).
"""

# ── scraper job types ─────────────────────────────────────────────────────────

JOB_NREGA_DISTRICT  = 'nrega_district'
JOB_NEWS_REFRESH    = 'news_refresh'
JOB_SOCIAL_REFRESH  = 'social_refresh'
JOB_PMKISAN_STATE   = 'pmkisan_state'
JOB_DATAGOV_FETCH   = 'datagov_fetch'    # pull official NREGA data from data.gov.in
JOB_DATAGOV_VERIFY  = 'datagov_verify'   # cross-verify our data against official data

# ── scraper job statuses ──────────────────────────────────────────────────────

STATUS_PENDING = 'pending'
STATUS_RUNNING = 'running'
STATUS_DONE    = 'done'
STATUS_FAILED  = 'failed'

# ── scheme names (must match what is stored in the schemes table) ─────────────

SCHEME_NREGA   = 'NREGA'
SCHEME_PMKISAN = 'PM-KISAN'
SCHEME_PMJAY   = 'PM-JAY'
SCHEME_PMAY    = 'PMAY-U'
SCHEME_UJJWALA = 'PM Ujjwala'
SCHEME_JJM     = 'Jal Jeevan Mission'

# ── domain → job type mapping (used by the rate limiter) ─────────────────────

JOB_DOMAIN = {
    JOB_NREGA_DISTRICT: 'deshseva.in',
    JOB_NEWS_REFRESH:   'news.google.com',
    JOB_SOCIAL_REFRESH: 'reddit.com',
    JOB_PMKISAN_STATE:  'pmkisan.gov.in',
    JOB_DATAGOV_FETCH:  'api.data.gov.in',
    JOB_DATAGOV_VERIFY: 'api.data.gov.in',
}
