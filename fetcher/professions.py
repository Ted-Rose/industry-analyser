"""Rule-based profession tagging for vacancy titles.

Pure, testable module — no ORM, no I/O (mirrors
``tv_programs/classification.py``). The taxonomy is IT-focused and
rule precedence is load-bearing.

``PROFESSION_RULES`` is an *ordered* list — first match wins. The
ordering is load-bearing (~91% of titles match ≥2 patterns):
the driver trap precedes the generic ``vadītājs`` → ``manager``
rule, IT sysadmins precede bare ``administrators``, IT architects
precede building architects, infosec precedes security guards,
and every specific dev/manager role precedes the generic buckets.
"""

from __future__ import annotations

import re

OTHER = 'other'

# Gender/noise chunks stripped before matching:
# "Programmētājs/-a", "(m/f/d)", "(vīr./siev.)" and other
# parenthetical noise like "(remote)".
_PARENS_RE = re.compile(r'\([^)]*\)')
# "Vadītājs/-a", "speciālists/-e" gender alternations.
_GENDER_SLASH_RE = re.compile(r'/-[a-zāčēģīķļņšūž]{1,3}\b')
# Seniority modifiers — a possible future second axis, stripped
# here so patterns stay short (plan §1 "Normalization").
_SENIORITY_RE = re.compile(
    r'\b(?:vecāk\w*|jaunāk\w*|seniors?|juniors?)\b'
)
# A leading "lead" is a seniority marker ("Lead Developer"); a
# trailing one is the role itself ("Tech Lead"), so only the
# leading position is stripped.
_LEADING_LEAD_RE = re.compile(r'^\s*lead\b')
_WS_RE = re.compile(r'\s+')


def normalize_title(title: str) -> str:
    """Lowercase the title and strip gender/seniority noise."""
    if not title:
        return ''
    s = title.casefold()
    s = _PARENS_RE.sub(' ', s)
    s = _GENDER_SLASH_RE.sub('', s)
    s = _SENIORITY_RE.sub(' ', s)
    s = _LEADING_LEAD_RE.sub(' ', s)
    return _WS_RE.sub(' ', s).strip()


# Ordered (profession_name, patterns) — first match wins. The
# 'other' entry is a trap for drivers so "kravas/auto vadītājs"
# never reaches the generic `vadītājs` → `manager` rule.
PROFESSION_RULES: list[tuple[str, tuple[str, ...]]] = [
    # An intern is an intern regardless of the field it mentions.
    ('intern', (
        r'\bpraktik',
        r'\bpraks',
        r'\bintern(?:ship)?s?\b',
        r'\bstažier',
    )),
    # Driver trap → other: must run before generic `vadītājs`.
    # `auto` is bounded so compounds like "autoparka vadītājs"
    # (fleet manager) fall through to `manager`.
    (OTHER, (
        r'\bšofer',
        r'\b(?:auto\b|automašīnas?|autobusa|kravas|iekrāvēja?|'
        r'vilcēja?|taksometra|taksi)\w*\s+(?:\w+\s+){0,2}vadītāj',
        r'\bautovadītāj',
        r'\bdriver\b',
    )),
    # Infosec before security-guard: "apsargs"/"drošības
    # inspektors" carry no IT prefix and fall through to `other`.
    ('it-security', (
        r'\b(?:informācijas|informāciju|it|ict|ikt)\s+drošīb',
        r'\bkiberdrošīb',
        r'\b(?:it|ict)\s+security',
        r'\binformation\s+security',
        r'\bcyber\s?security',
        r'\binfosec\b',
        r'\bsecurity\s+(?:engineer|analyst|specialist|'
        r'consultant|architect|officer)',
        r'\bpenetration\s+test|\bpentest',
    )),
    # Sysadmin before office-admin: bare "administrators" falls
    # through to `other`.
    ('sysadmin', (
        r'\bsysadmin',
        r'\b(?:system|network|infrastructure|server|database|'
        r'linux|windows|it|ict)\s+administrator',
        r'\bdba\b',
        r'\w*sistēm\w*\s+administrator',
        r'\b(?:datortīkl|tīkl|infrastruktūr|server|datubāz|'
        r'datu\s+bāz)\w*\s+administrator',
        r'\bsistēmadministrator',
        r'\bit\s+administrator',
    )),
    # IT architect before building architect: bare "arhitekts"
    # falls through to `other`.
    ('it-architect', (
        r'\b(?:solution|software|technical|technology|data|'
        r'enterprise|infrastructure|cloud|it|ict)\s+architect',
        r'\b(?:risinājumu|tehnoloģij\w*|datu|infrastruktūras|'
        r'cloud|it|ikt)\s+arhitekt',
        r'\w*sistēm\w*\s*arhitekt',
    )),
    ('qa-engineer', (
        r'\bqa\b',
        r'\btestētāj',
        r'\btest\s+(?:engineer|automation|analyst|lead|manager|'
        r'specialist)',
        r'\bautomation\s+(?:test|qa|engineer)',
        r'\bquality\s+(?:assurance|engineer|control)',
        r'\b(?:manual|automation)\s+tester',
        r'\btester\b',
        r'\bqc\s+engineer',
    )),
    ('data-scientist', (
        r'\bdata\s+scien',
        r'\bdatu\s+zinātnie',
        r'\bmachine\s+learning',
        r'\bdeep\s+learning',
        r'\bartificial\s+intelligence',
        r'\b(?:ml|ai)\s+engineer',
        r'\bmlops\b',
        r'\bllm\b',
    )),
    ('data-engineer', (
        r'\bdata\s+engineer',
        r'\bdatu\s+inženier',
        r'\bdwh\b',
        r'\betl\b',
        r'\bbig\s+data\b',
        r'\bdata\s+(?:platform|pipeline)',
    )),
    ('data-analyst', (
        r'\bdata\s+anal',
        r'\bdatu\s+analītiķ',
        r'\bbi\s+(?:analyst|developer|consultant|izstrādātāj|'
        r'programmētāj)',
        r'\bbusiness\s+intelligence',
        r'\bpower\s*bi',
    )),
    # Specific before generic: "biznesa/sistēmanalītiķis" is
    # matched here; bare "analītiķis" falls through to `other`.
    ('business-analyst', (
        r'\w*sistēm\w*\s*analītiķ',
        r'\bbiznesa\s+analītiķ',
        r'\bbusiness\s+anal',
        r'\bit\s+analītiķ',
        r'\brequirements\s+anal',
        r'\bfunctional\s+anal',
    )),
    ('devops-engineer', (
        r'\bdev\s*ops\b',
        r'\bsite\s+reliability',
        r'\bsre\b',
        r'\bplatform\s+engineer',
        r'\bcloud\s+engineer',
        r'\binfrastructure\s+engineer',
    )),
    ('mobile-developer', (
        r'\b(?:ios|android|mobile|flutter|kotlin|swift)\s+'
        r'(?:app\s+)?(?:developer|izstrādātāj|programmētāj|'
        r'engineer)',
        r'\breact\s+native',
        r'\bmobil\w*\s+(?:lietotn|aplikācij)\w*\s+'
        r'(?:izstrādātāj|programmētāj|developer)',
    )),
    ('frontend-developer', (
        r'\bfront[\s-]?end',
        r'\bfronta\s+izstrādātāj',
        r'\b(?:react|angular|vue|svelte)\s+(?:developer|'
        r'izstrādātāj|programmētāj|engineer)',
    )),
    ('backend-developer', (
        r'\bback[\s-]?end',
        r'\bservera\s+puses\s+izstrādātāj',
    )),
    ('fullstack-developer', (
        r'\bfull[\s-]?stack',
    )),
    ('ux-designer', (
        r'\bux\b',
        r'\bui[\s/]*ux\b|\bux[\s/]*ui\b',
        r'\bui\s+(?:designer|dizainer|engineer)',
        r'\bproduct\s+designer',
        r'\blietotāju\s+pieredz',
        r'\bweb\s*designer|\bwebdizainer',
    )),
    # ERP/CRM/SAP vendors classify as it-consultant wherever they
    # appear (plan §1 row 14) — before the generic dev bucket.
    ('it-consultant', (
        r'\bit\s+konsultant',
        r'\bit\s+consultant',
        r'\b(?:sap|erp|crm|salesforce|dynamics|navision|odoo)\b',
    )),
    ('it-support', (
        r'\b(?:it|ict|ikt)\s+(?:atbalst|support|palīdzīb)',
        r'\blietotāju\s+atbalst',
        r'\btehnisk\w*\s+(?:atbalst|palīdzīb)',
        r'\b(?:technical|tech|it)\s+support',
        r'\bsupport\s+engineer',
        r'\bservice\s*desk',
        r'\bhelp\s*desk',
        r'\b(?:first|1st|second|2nd)\s*[\s-]?line\s+support',
    )),
    # Tech/team/engineering lead — "izstrādes vadītājs" is the
    # LV twin. A leading bare "lead" was already normalized away.
    ('tech-lead', (
        r'\b(?:tech|team|engineering|development|software|'
        r'technical)[\s-]*lead\b',
        r'\bteamlead',
        r'\bizstrādes\s+vadītāj',
        r'\b(?:engineering|development)\s+manager',
    )),
    ('product-manager', (
        r'\bproduct\s+(?:owner|manager|lead)',
        r'\bprodukt[au]?\s+vadītāj',
        r'\bprodukt[au]?\s+īpašniek',
    )),
    # "projektu vadītājs" even when compounded ("pārdošanas
    # projektu vadītājs").
    ('project-manager', (
        r'\bprojekt[au]?\s+vadītāj',
        r'\bprojekt[au]?\s+koordinator',
        r'\bproject\s+(?:manager|coordinator|lead|director)',
        r'\bscrum\s+master',
    )),
    ('it-manager', (
        r'\b(?:it|ict|ikt)\s+(?:nodaļas\s+|departamenta\s+|'
        r'daļas\s+|grupas\s+|komandas\s+)?vadītāj',
        r'\b(?:it|ict)\s+manager',
        r'\binformācijas\s+tehnoloģij\w*\s+vadītāj',
        r'\bhead\s+of\s+(?:it|ict|technology)',
        r'\bcio\b',
        r'\bchief\s+information\s+officer',
    )),
    ('executive', (
        r'\b(?:ceo|cto|cfo|coo|cmo)\b',
        r'\bchief\b',
        r'\bco[\s-]?founder|\bfounder\b',
        r'\bīpašniek|\blīdzīpašniek',
        r'\bvaldes\s+(?:locekl|priekšsēdētāj)',
        # \w* prefix catches LV compounds — izpild-/komers-/
        # finanšu-direktors are all executive roles.
        r'\w*direktor',
        r'\bdirector\b',
        r'\bmanaging\s+director',
        r'\bboard\s+member',
        r'\bpresident\b',
    )),
    # Generic dev bucket — after every specific dev role and the
    # consultant/support buckets.
    ('software-developer', (
        r'\bprogrammētāj',
        r'\bizstrādātāj',
        r'\bsoftware\s+(?:developer|engineer|programmer)',
        r'\bdevelopers?\b',
        r'\bprogrammers?\b',
        r'\bcoders?\b|\bkodētāj',
        r'\bprogrammēšanas\s+inženier',
        r'\bprogrammatūr\w*\s*inženier',
        r'\w*sistēm\w*\s*inženier',
    )),
    # Generic manager bucket — "vadītājs", "head of" etc. catch
    # the non-IT management tail too (a meaningful filter).
    ('manager', (
        r'\bvadītāj',
        r'\bmanagers?\b|\bmenedžer',
        r'\bpārzi[ņn]',
        r'\bhead\s+of',
        r'\bsupervisor',
        r'\bkoordinator',
    )),
]

# Distinct names in declaration order — the Profession rows the
# backfill command upserts ('other' included via the driver trap).
PROFESSION_NAMES: tuple[str, ...] = tuple(
    dict.fromkeys(
        [name for name, _ in PROFESSION_RULES] + [OTHER]
    )
)


_COMPILED_RULES: tuple[tuple[str, tuple[re.Pattern, ...]], ...] = (
    tuple(
        (
            name,
            tuple(
                re.compile(p, re.IGNORECASE) for p in patterns
            ),
        )
        for name, patterns in PROFESSION_RULES
    )
)


def classify(title: str, content: str = '') -> str:
    """Return the first matching ``Profession.name`` for a title.

    ``content`` (the ``_extract_searchable_content`` blob) is
    accepted but unused in v1 — reserved as a tiebreaker for
    compound titles later. Untitled/empty titles and everything
    unmatched return ``'other'``.
    """
    normalized = normalize_title(title)
    if not normalized:
        return OTHER
    for name, patterns in _COMPILED_RULES:
        if any(p.search(normalized) for p in patterns):
            return name
    return OTHER
