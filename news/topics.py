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
            'deputāts', 'opozīcija',
            'likumprojekts', 'referend*', 'Satversm*',
            'premjerministr*', 'premjera*', 'premjeru*',
            '=premjers', 'parlaments',
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
    {
        'slug': 'war',
        'name': 'Karš',
        'weight': 1.1,
        'keywords': [
            # 'karš' (war) declensions as EXACT tokens — a
            # 'kara*' prefix would also hit 'karalis'/
            # 'karaliskā' (royals) and 'karate', and 'karu*'
            # would hit 'karuselis'. '=karu' (instr./gen.pl.)
            # is still safe: 'karuselis' is a different
            # token. The 'karavīr*'/'karaspēk*'/'karadarb*'
            # families cover the compounds a 'kara*' prefix
            # would have reached.
            '=karš', '=kara', '=karam', '=karā', '=karu',
            '=kari', '=karus', '=karos',
            'karavīr*', 'karaspēk*', 'karadarb*',
            # 'uzbrukum*'/'pretuzbrukum*' are also sports
            # terms (attack phase/counter-attack) and
            # 'raķeš*' covers space launches — accepted
            # ambiguity, war usage dominates. 'dron*' even
            # hits 'dronlaps'.
            'uzbrukum*', 'pretuzbrukum*', 'raķeš*', 'dron*',
            'sprādzi*', 'apšaud*', 'bruņot*', 'militā*',
            'armij*', 'kauj*',
            'okupācij*', 'aneksij*', 'mobilizācij*',
        ],
    },
    {
        'slug': 'diplomacy',
        'name': 'Diplomātija',
        'weight': 1.0,
        'keywords': [
            # 'diplomā*'/'sankcij*'/'=NATO'/'=ārlietu' and
            # '=ārlietu ministr*' moved here from politics —
            # a keyword in two topics double-scores.
            # 'vēstniecīb*' adds the embassy family
            # 'vēstniek*' cannot reach ('vēstniecība' starts
            # 'vēstniec', not 'vēstniek'). '=ANO' is the UN
            # acronym token.
            'diplomā*', 'sankcij*', '=NATO', '=ANO',
            'samit*', 'vizīt*', 'vēstniek*', 'vēstniecīb*',
            'rezolūcij*', '=ārlietu', '=ārlietu ministr*',
        ],
    },
)
