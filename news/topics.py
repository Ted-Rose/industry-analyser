"""Seed topic definitions — Latvian keywords matched against
title + lead tokens. Each keyword word carries an optional
marker (see news.classification):

  '=word'  EXACT  — literal token, unstemmed ('=Latvenergo'
                    cannot hit 'Latvijas')
  'word*'  PREFIX — token startswith ('premjer*' hits
                    'premjerministrs'/'premjeru', not 'premija')
  'word'   STEM   — 4-char stem (news.clustering.text_stems):
                    'Saeimas' hits 'Saeima'

Why the curation below matters: 4-char stems are too greedy
for short roots — 'Latvenergo'->'latv' matched every
Latvijas/latviešu token, 'eiro'/'eirozona'->'eiro' matched
all Eiropas* tokens, 'līdzfinansējums'->'līdz' matched the
preposition 'līdz' itself (kept because classification stems
with drop_stopwords=False), 'eksports'->'eksp' matched
eksperts, 'premjers'->'prem' matched premija,
'partija'->'part' matched partneris, 'banka'->'bank' matched
bankomāts/bankrotē, 'grants'->'gran' matched granāta and
'elektroauto'->'elek' matched elektrība/elektroenerģija.
Words on such roots use '='/'*' forms or safe inflections —
e.g. 'banka*','bankā*','banku*' because 'bankām'/'bankās'
start 'bankā', not 'banka', and plain 'banku' would re-stem
to 'bank'.

Multi-word keywords hit only when ALL their word-specs match,
order-independent ('ES fondi' needs both 'es' and 'fond')."""

TOPICS = (
    {
        'slug': 'economics',
        'name': 'Ekonomika',
        'weight': 1.2,
        'keywords': [
            'ekonomika', 'inflācij*', 'bezdarbs', 'alga', 'algas',
            'nodokl*', 'nodokļ*', 'eksport*', 'import*', 'IKP',
            '=eiro', 'eirozon*',
            # 'banka*' also hits 'bankas' meaning jars
            # ('Konservu bankas') — an inherent ambiguity,
            # accepted rather than curated away.
            'banka*', 'bankā*', 'banku*',
            'akcijas', 'tirgus', 'recesij*', 'cenas', 'tarif*',
            '=Latvenergo', 'elektroenerģij*', 'elektrīb*',
            'EKB', 'ECB', 'nafta', 'birža', 'investīcij*',
            'procentu likmes',
        ],
    },
    {
        'slug': 'politics',
        'name': 'Politika',
        'weight': 1.0,
        'keywords': [
            'Saeima', 'valdīb*', 'koalīcij*', 'ministrij*',
            '=ministrs', '=ministra', '=ministram',
            'ministru*', 'ministri*', 'ministre*',
            'partij*', 'vēlēšan*', 'prezident*',
            'deputāts', 'opozīcija', 'NATO', 'sankcijas',
            'likumprojekts', 'referend*', 'Satversm*',
            'premjerministr*', 'premjera*', 'premjeru*',
            '=premjers', 'parlaments',
            '=ārlietu', '=ārlietu ministr*', 'diplomā*',
            'aizsardzības ministrij*',
        ],
    },
    {
        'slug': 'government-funding',
        'name': 'Valsts finansējums',
        'weight': 1.3,
        'keywords': [
            'budžets', 'finansējums', 'subsīdij*', 'dotācija',
            'līdzfinansējum*',
            # 'ES fondi' needs the 'es' stem — also the
            # pronoun — plus 'fond'. Both stems must hit,
            # so pronoun noise alone cannot trigger it.
            'ES fondi', 'ALTUM',
            'elektroauto*', 'elektromobi*',
            'atbalsta programma', 'grant*', 'nodokļu atlaides',
            'Eiropas Savienības fondi', 'investīciju atbalsts',
            'pašvaldību finanšu', 'dotācijas',
        ],
    },
)
