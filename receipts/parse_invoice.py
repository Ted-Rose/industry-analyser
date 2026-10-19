"""Deterministic parser for the Rimi e-shop invoice text layer
(plan §5.2 step 3).

The ``ir izpildīts`` e-shop mail carries an ``invoice*.pdf`` whose
text layer ``pypdf`` reads directly; image-only e-receipt PDFs go
through the AI extraction path instead. Layout assumptions made
here are verified by ``ingest.reconcile()`` — wrong rows land as
``total_mismatch``/``parse_error``, never silently trusted.

Every returned dict has the same shape ``ingest`` consumes:
store/address/vat/document fields, ``purchased_at``, ``total``,
``total_discount``, ``payment_method``, ``items`` and the optional
``vat_totals`` (per-VAT-rate gross amounts for the §5.4 VAT
cross-check).
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.utils import timezone

_NUM = r'-?\d+(?:[,.]\d+)?'
_UNITS = r'gab|kg|kompl|metri|m'

# Item line: "<name> <qty> <unit> <unit_price> [<discount>] <total>".
# The discount-column variant is tried first; both are anchored at
# the end of the line so the two shapes cannot collide.
_ITEM_DISCOUNT_RE = re.compile(
    rf'^(?P<name>\S.*?)\s+'
    rf'(?P<qty>{_NUM})\s*(?P<unit>{_UNITS})\s+'
    rf'(?P<unit_price>{_NUM})\s+'
    rf'(?P<discount>{_NUM})\s+'
    rf'(?P<total>{_NUM})\s*$',
    re.IGNORECASE,
)
_ITEM_RE = re.compile(
    rf'^(?P<name>\S.*?)\s+'
    rf'(?P<qty>{_NUM})\s*(?P<unit>{_UNITS})\s+'
    rf'(?P<unit_price>{_NUM})\s+'
    rf'(?P<total>{_NUM})\s*$',
    re.IGNORECASE,
)
# VAT summary row: optional class letter, rate %, then base / vat /
# gross ('ar PVN') amounts — only the 3-amount shape feeds
# ``vat_totals``.
_VAT_ROW_RE = re.compile(
    rf'^\s*(?P<vat_class>[ACF])?\s*(?P<rate>\d{{1,2}}(?:[,.]\d+)?)'
    rf'\s*%\s+{_NUM}\s+{_NUM}\s+(?P<gross>{_NUM})\s*$',
    re.IGNORECASE,
)
_DOC_RE = re.compile(
    r'r[ēe][ķk]ins[^\d\n]{0,15}?(\d[\w/-]*)', re.IGNORECASE)
_REGISTER_RE = re.compile(
    r'kase\s*(?:nr\.?)?\s*:?\s*(\d+)', re.IGNORECASE)
_VAT_NUMBER_RE = re.compile(r'\bLV\s?\d{11}\b')
_DATE_RE = re.compile(
    r'(\d{1,2})[./](\d{1,2})[./](\d{2,4})'
    r'(?:\s+(\d{1,2}):(\d{2}))?')
_TOTAL_RE = re.compile(r'kop[aāa]|pavisam|apmaksai|total', re.IGNORECASE)
_DATE_HINT_RE = re.compile(r'datums|izdots|izrakst', re.IGNORECASE)
_DISCOUNT_RE = re.compile(r'atlaide|atlaid|ietaup', re.IGNORECASE)
_NUMBER_TAIL_RE = re.compile(rf'({_NUM})\s*$')
_ADDRESS_RE = re.compile(r'LV-\d{4}|iela|iel\.', re.IGNORECASE)
_PAYMENT_RE = re.compile(
    r'maksājuma\s+veids\s*:?\s*(.*)|bankas\s+karte|'
    r'maksājuma\s+karte|skaidr\w*\s+naud\w*',
    re.IGNORECASE,
)
_FEE_KEYWORDS = ('piegād', 'depozīt', 'iepakojum', 'pakošan')


def _to_decimal(text):
    """'1 234,56' / '1.234,56'-ish → Decimal; None on failure."""
    if text is None:
        return None
    cleaned = (
        str(text).replace('\xa0', '').replace(' ', '')
        .replace(',', '.')
    )
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_date_lines(lines):
    """First valid date on lines carrying a date hint keyword."""
    for line in lines:
        if not _DATE_HINT_RE.search(line):
            continue
        parsed = _parse_date_text(line)
        if parsed is not None:
            return parsed
    return None


def _parse_date_text(text):
    """First valid dd.mm.yyyy (+optional hh:mm) in the text."""
    for match in _DATE_RE.finditer(text):
        day, month, year = (
            int(match.group(1)), int(match.group(2)),
            int(match.group(3)),
        )
        if year < 100:
            year += 2000
        hour = int(match.group(4) or 0)
        minute = int(match.group(5) or 0)
        try:
            naive = datetime(year, month, day, hour, minute)
        except ValueError:
            continue
        return timezone.make_aware(naive)
    return None


def _last_number(line):
    match = _NUMBER_TAIL_RE.search(line)
    return _to_decimal(match.group(1)) if match else None


def _is_fee(name):
    lowered = name.lower()
    return any(keyword in lowered for keyword in _FEE_KEYWORDS)


def _parse_items(lines):
    items = []
    for line in lines:
        match = _ITEM_DISCOUNT_RE.match(line) or _ITEM_RE.match(line)
        if match is None:
            continue
        groups = match.groupdict()
        name = groups['name'].strip()
        if not name:
            continue
        items.append({
            'raw_name': name[:300],
            'quantity': _to_decimal(groups['qty']) or Decimal(1),
            'unit': groups['unit'].lower()[:10],
            'unit_price': _to_decimal(groups['unit_price']),
            'discount': _to_decimal(groups.get('discount'))
            or Decimal(0),
            'total': _to_decimal(groups['total']) or Decimal(0),
            'vat_class': '',
            'vat_rate': None,
            'is_fee': _is_fee(name),
            'position': len(items) + 1,
        })
    return items


def _parse_vat_totals(lines):
    totals = {}
    for line in lines:
        match = _VAT_ROW_RE.match(line)
        if match is None:
            continue
        gross = _to_decimal(match.group('gross'))
        if gross is None:
            continue
        rate = (_to_decimal(match.group('rate')) or Decimal(0))
        key = str(rate.normalize())
        totals[key] = totals.get(key, Decimal(0)) + gross
    return totals


def _first_nonempty_line(lines):
    for line in lines:
        if line.strip():
            return line.strip()
    return ''


def _find_payment_method(lines):
    for line in lines:
        match = _PAYMENT_RE.search(line)
        if match is None:
            continue
        if match.group(1):
            return match.group(1).strip()[:50]
        return match.group(0).strip()[:50]
    return ''


def parse_invoice_text(text):
    """Parse a pypdf text layer into the normalized receipt dict."""
    lines = [line.strip() for line in text.splitlines()]
    doc_match = _DOC_RE.search(text)
    register_match = _REGISTER_RE.search(text)
    vat_match = _VAT_NUMBER_RE.search(text)

    total = None
    total_discount = Decimal(0)
    seen_discounts = set()
    store_address = ''
    for line in lines:
        lowered = line.lower()
        if _TOTAL_RE.search(line) and 'bez' not in lowered:
            number = _last_number(line)
            if number is not None:
                total = number   # last matching line wins
        elif _DISCOUNT_RE.search(line):
            number = _last_number(line)
            # Identical amounts are deduped: a header+footer
            # repetition of the same discount must not
            # double-count total_discount.
            if number is not None:
                value = abs(number)
                if value not in seen_discounts:
                    seen_discounts.add(value)
                    total_discount += value
        if not store_address and _ADDRESS_RE.search(line):
            store_address = line[:300]

    lowered_text = text.lower()
    return {
        'chain': 'rimi' if 'rimi' in lowered_text else '',
        'store_name': _first_nonempty_line(lines)[:200],
        'store_address': store_address,
        'vat_number': (
            vat_match.group(0).replace(' ', '')
            if vat_match else ''
        ),
        'register_number': (
            register_match.group(1) if register_match else ''
        ),
        'document_number': (
            doc_match.group(1) if doc_match else ''
        )[:50],
        'purchased_at': (
            _parse_date_lines(lines) or _parse_date_text(text)
        ),
        'currency': 'EUR',
        'total': total,
        'total_discount': total_discount,
        'payment_method': _find_payment_method(lines),
        'items': _parse_items(lines),
        'vat_totals': _parse_vat_totals(lines),
    }
