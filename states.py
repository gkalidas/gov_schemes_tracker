"""
Geographic and entity data.

To add a new state for NREGA scraping: add an entry to NREGA_STATES.
To add a state for PM-KISAN: add it to PMKISAN_STATES.
To add a new entity for news/social coverage: add a tuple to NEWS_ENTITIES.
Nothing else needs to change.
"""

# state-slug (as used in DeshSeva URLs) → list of district slugs
NREGA_STATES = {
    'rajasthan': [
        'ajmer', 'alwar', 'banswara', 'baran', 'barmer', 'bharatpur',
        'bhilwara', 'bikaner', 'bundi', 'chittorgarh', 'churu', 'dausa',
        'dholpur', 'dungarpur', 'hanumangarh', 'jaipur', 'jaisalmer',
        'jalore', 'jhalawar', 'jhunjhunu', 'jodhpur', 'karauli', 'kota',
        'nagaur', 'pali', 'pratapgarh', 'rajsamand', 'sawai-madhopur',
        'sikar', 'sirohi', 'sri-ganganagar', 'tonk', 'udaipur',
    ],
    'bihar': [
        'araria', 'arwal', 'aurangabad', 'banka', 'begusarai', 'bhagalpur',
        'bhojpur', 'buxar', 'darbhanga', 'east-champaran', 'gaya',
        'gopalganj', 'jamui', 'jehanabad', 'kaimur', 'katihar', 'khagaria',
        'kishanganj', 'lakhisarai', 'madhepura', 'madhubani', 'munger',
        'muzaffarpur', 'nalanda', 'nawada', 'patna', 'purnia', 'rohtas',
        'saharsa', 'samastipur', 'saran', 'sheikhpura', 'sheohar',
        'sitamarhi', 'siwan', 'supaul', 'vaishali', 'west-champaran',
    ],
    'madhya-pradesh': [
        'agar-malwa', 'alirajpur', 'anuppur', 'ashoknagar', 'balaghat',
        'barwani', 'betul', 'bhind', 'bhopal', 'burhanpur', 'chhatarpur',
        'chhindwara', 'damoh', 'datia', 'dewas', 'dhar', 'dindori', 'guna',
        'gwalior', 'harda', 'hoshangabad', 'indore', 'jabalpur', 'jhabua',
        'katni', 'khandwa', 'khargone', 'mandla', 'mandsaur', 'morena',
        'narsinghpur', 'neemuch', 'panna', 'raisen', 'rajgarh', 'ratlam',
        'rewa', 'sagar', 'satna', 'sehore', 'seoni', 'shahdol', 'shajapur',
        'sheopur', 'shivpuri', 'sidhi', 'singrauli', 'tikamgarh', 'ujjain',
        'umaria', 'vidisha',
    ],
    'jharkhand': [
        'bokaro', 'chatra', 'deoghar', 'dhanbad', 'dumka',
        'east-singhbhum', 'garhwa', 'giridih', 'godda', 'gumla',
        'hazaribagh', 'jamtara', 'khunti', 'koderma', 'latehar',
        'lohardaga', 'pakur', 'palamu', 'ramgarh', 'ranchi', 'sahebganj',
        'seraikela-kharsawan', 'simdega', 'west-singhbhum',
    ],
    'uttar-pradesh': [
        'agra', 'aligarh', 'allahabad', 'ambedkar-nagar', 'amethi',
        'amroha', 'auraiya', 'azamgarh', 'baghpat', 'bahraich', 'ballia',
        'balrampur', 'banda', 'barabanki', 'bareilly', 'basti', 'bhadohi',
        'bijnor', 'budaun', 'bulandshahr', 'chandauli', 'chitrakoot',
        'deoria', 'etah', 'etawah', 'farrukhabad', 'fatehpur', 'firozabad',
        'gautam-buddha-nagar', 'ghaziabad', 'ghazipur', 'gonda',
        'gorakhpur', 'hamirpur', 'hapur', 'hardoi', 'hathras', 'jalaun',
        'jaunpur', 'jhansi', 'kannauj', 'kanpur-dehat', 'kanpur-nagar',
        'kasganj', 'kaushambi', 'kushinagar', 'lakhimpur-kheri', 'lalitpur',
        'lucknow', 'maharajganj', 'mahoba', 'mainpuri', 'mathura', 'mau',
        'meerut', 'mirzapur', 'moradabad', 'muzaffarnagar', 'pilibhit',
        'pratapgarh', 'rae-bareli', 'rampur', 'saharanpur', 'sambhal',
        'sant-kabir-nagar', 'shahjahanpur', 'shamli', 'shravasti',
        'siddharthnagar', 'sitapur', 'sonbhadra', 'sultanpur', 'unnao',
        'varanasi',
    ],
}

# States to scrape PM-KISAN beneficiary data for.
PMKISAN_STATES = [
    'RAJASTHAN', 'BIHAR', 'UTTAR PRADESH', 'MADHYA PRADESH', 'JHARKHAND',
    'ODISHA', 'WEST BENGAL', 'ANDHRA PRADESH', 'TELANGANA', 'KARNATAKA',
]

# (level, entity_name, scheme) tuples seeded into the news/social refresh queue.
# level: 'union' | 'state' | 'district'
NEWS_ENTITIES = [
    ('union', 'INDIA',          'NREGA'),
    ('state', 'RAJASTHAN',      'NREGA'),
    ('state', 'BIHAR',          'NREGA'),
    ('state', 'UTTAR PRADESH',  'NREGA'),
    ('state', 'MADHYA PRADESH', 'NREGA'),
    ('state', 'JHARKHAND',      'NREGA'),
]
