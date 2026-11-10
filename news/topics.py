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
            'budžets',
            # 'finansējum*' not 'finansējums' — a plain word
            # 4-char-stems to 'fina' and matched every
            # 'finanšu …' phrase (sanctions, parenting
            # features); the prefix still catches all real
            # declensions ('finansējums'/'finansējuma').
            'finansējum*', 'subsīdij*', 'dotācija',
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
            # 'raķeš*'/'raķet*' cover space launches too —
            # accepted ambiguity, war usage dominates.
            # 'raķeš*' alone misses the nominative
            # 'raķete'/'raķetes', so both prefixes are seeded.
            # 'dron*' even hits 'dronlaps'.
            'uzbrukum*', 'pretuzbrukum*', 'raķeš*', 'raķet*',
            'dron*',
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
    # 'crime' is deliberately LAST in TOPICS: score ties
    # resolve to the first topic in pk order (seeds are
    # created in tuple order), so an article equally matching
    # crime and a higher-weighted topic keeps the heavier tag
    # and the 0.4 weight cannot capture ambiguous hard news.
    # The tagging itself is the demotion — an untopicked
    # story scores at effective weight 1.0 (_refresh_story
    # defaults NULL to 1.0), while a 'crime'-tagged story
    # scores 0.4: a multi-outlet crime story drops below
    # lower-coverage economics/politics stories yet still
    # surfaces when coverage is broad.
    {
        'slug': 'crime',
        'name': 'Noziedzība',
        'weight': 0.4,
        'keywords': [
            'nozieg*', 'noziedz*', 'slepkav*', 'nogalin*',
            # 'zagt*'/'zagl*' cover 'zagt'/'zagta'/'zaglis';
            # 'zādz*' covers 'zādzība' — a different root.
            'zādz*', 'zagl*', 'zagt*',
            # 'cietum*' covers 'cietumsods'/'cietumā'/
            # 'cietumnieks'; 'cietis' (suffered) stems
            # 'cieti' — safe.
            'cietum*', 'ieslodz*', 'noties*', 'piesprie*',
            # '=soda'/'=sods'/'=sodu' are EXACT declensions
            # of 'sods' (sentence/penalty); 'soda' the drink
            # is an accepted rare false positive (precedent:
            # 'banka*' also hits jars).
            '=soda', '=sods', '=sodu',
            'policij*', 'prokur*', 'kriminā*',
            # 'tiesas*' (of court) and '=tiesa' avoid a
            # 'ties*' stem/prefix that would hit 'tiesības'/
            # 'tiesu'/'tieši'.
            'tiesas*', 'tiesneš*', '=tiesa', 'prāv*',
            'aiztur*', 'apcietin*', 'aizdom*',
            'krāpniec*', 'krāpš*', 'blēdīb*',
            'izvaro*', 'vardarb*', 'narkot*',
            'nolaup*', 'teror*', 'šantāž*',
            'dzērāj*', 'muit*', 'kontraband*',
            # 'cilvēku tirdzniecīb*' needs BOTH the 'cilv'
            # stem and the 'tirdzniecīb*' prefix — generic
            # trade talk without a 'cilvēk*' token cannot
            # hit.
            'cilvēku tirdzniecīb*',
            # 'Valsts robežsardz*' — border-guard smuggling/
            # crossing cases; the 'vals' stem and the
            # 'robežsardz*' prefix are both required.
            'Valsts robežsardz*',
            # Deliberately absent:
            #  'korupc*'/'korump*'/'=KNAB' — corruption
            #   coverage is usually politically significant
            #   (officials, institutions); demoting it to
            #   0.4 would bury the accountability stories
            #   the digest exists to rank high. They keep
            #   hitting politics/economics keywords.
            #  'ieroc*' — weapons keywords would drag
            #   Ukraine arms-supply stories out of 'war'
            #   into a 0.4 topic.
            #  'šāv*'/'nošāv*' — 'šāvējs' is a sport
            #   shooter; sports pages would tag 'crime'.
            #  'ties*' as a stem — hits 'tiesības'/'tiesu'/
            #   'tieši'; the 'tiesas*'/'tiesneš*'/'=tiesa'
            #   forms above cover court vocabulary safely.
            #  'pārkāpum*' — too broad (sanctions/rules
            #   violations, not just criminal offences).
            #  'miruš*'/'miris' — obituaries and accidents
            #   are not crime.
        ],
    },
)
