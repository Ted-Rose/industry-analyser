"""Seed topic definitions — keywords are Latvian words matched
as 4-char stems (news.clustering.text_stems) against stemmed
title + lead text, so inflected forms hit ("Saeimas" matches
'Saeima'). Multi-word keywords hit only when ALL their stems
are present, order-independent."""

TOPICS = (
    {
        'slug': 'economics',
        'name': 'Ekonomika',
        'weight': 1.2,
        'keywords': [
            'ekonomika', 'inflācija', 'bezdarbs', 'alga', 'algas',
            'nodokļi', 'nodoklis', 'eksports', 'imports', 'IKP',
            'eiro', 'banka', 'akcijas', 'tirgus', 'recesija',
            'cenas', 'tarifi', 'Latvenergo', 'elektroenerģija',
            'eirozona', 'EKB', 'ECB', 'nafta', 'birža',
            'investīcijas', 'procentu likmes',
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
            'premjers', 'premjerministrs', 'parlaments',
            'ārlietu', 'diplomātija', 'aizsardzības ministrija',
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
            'Eiropas Savienības fondi', 'investīciju atbalsts',
            'pašvaldību finanšu', 'dotācijas', 'subsīdijas',
        ],
    },
)
