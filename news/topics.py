"""Seed topic definitions — keywords are Latvian stems matched
\b-bounded against lowercased title + lead text."""

TOPICS = (
    {
        'slug': 'economics',
        'name': 'Ekonomika',
        'weight': 1.2,
        'keywords': [
            'ekonomika', 'inflācija', 'bezdarbs', 'alga', 'algas',
            'nodokļi', 'nodoklis', 'eksports', 'imports', 'IKP',
            'eiro', 'banka', 'akcijas', 'tirgus', 'recesija',
            'cenas', 'tarifi', 'Latvenergo',
        ],
    },
    {
        'slug': 'politics',
        'name': 'Politika',
        'weight': 1.0,
        'keywords': [
            'Saeima', 'valdība', 'ministrs', 'ministrija',
            'koalīcija', 'partija', 'vēlēšanas', 'prezidents',
            'deputāts', 'opozīcija', 'NATO', 'sankcijas',
            'likumprojekts', 'referendum', 'Satversme',
        ],
    },
    {
        'slug': 'government-funding',
        'name': 'Valsts finansējums',
        'weight': 1.3,
        'keywords': [
            'budžets', 'finansējums', 'subsīdija', 'dotācija',
            'ES fondi', 'līdzfinansējums', 'ALTUM', 'elektroauto',
            'atbalsta programma', 'grants', 'nodokļu atlaides',
        ],
    },
)
