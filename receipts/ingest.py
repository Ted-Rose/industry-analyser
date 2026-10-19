"""Email → Receipt ingestion pipeline (plan §5.2).

Transport-agnostic: ``process_message`` takes a parsed
``EmailMessage`` (not an IMAP handle), so a future push-intake
endpoint (plan §10) can reuse the same entry point.

Per PDF attachment: sha256 dedup → pypdf text layer → invoice
parser, or JobClient multimodal for image-only PDFs →
``reconcile()`` (§5.4) → ``Receipt`` + ``ReceiptItem`` rows in one
``transaction.atomic()`` → per-user ``CategoryRule`` pass.
Deterministic parse failures write a ``parse_error`` receipt row
so the message can be marked ``\\Seen`` instead of retrying
forever; transient/cap/config failures (``AIJobError``)
propagate so the command aborts the run and leaves the message
UNSEEN for retry.
"""

import hashlib
import json
import logging
import os
import re
import traceback
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db import IntegrityError, transaction
from django.utils import timezone

from ai_providers.errors import AIJobError
from ai_providers.types import (
    GenerationOptions,
    ImagePart,
    PromptSpec,
)
from pypdf import PdfReader

from .models import CategoryRule, Product, Receipt, ReceiptItem, Store
from .parse_invoice import parse_invoice_text

logger = logging.getLogger('receipts')

ITEMS_SUM_TOLERANCE = Decimal('0.03')
LINE_TOLERANCE = Decimal('0.02')

_PROMPT_PATH = os.path.join(
    os.path.dirname(__file__), 'prompts', 'receipt_extract.txt')
_prompt_text = None

_FILENAME_DOC_RE = re.compile(r'^([A-Za-z0-9]+)-([A-Za-z0-9]+)$')


@dataclass
class MessageResult:
    """Per-message processing tallies returned by process_message."""
    created: int = 0        # Receipt rows written
    skipped: int = 0        # attachments already imported (sha256)
    errors: int = 0         # attachments that failed (parse_error)
    ai_pending: int = 0     # dry-run: would have called the AI path


def _load_prompt():
    global _prompt_text
    if _prompt_text is None:
        with open(_PROMPT_PATH, 'r', encoding='utf-8') as f:
            _prompt_text = f.read()
    return _prompt_text


def iter_pdf_attachments(email_msg):
    """Yield ``(filename, pdf_bytes)`` for each PDF part."""
    for part in email_msg.walk():
        filename = part.get_filename() or ''
        is_pdf = part.get_content_type() == 'application/pdf' or (
            filename.lower().endswith('.pdf')
        )
        if not is_pdf:
            continue
        payload = part.get_payload(decode=True)
        if payload:
            yield filename or 'attachment.pdf', payload


def _extract_pdf_text(pdf_bytes):
    """pypdf text layer, stripped; '' for image-only PDFs."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return '\n'.join(
        page.extract_text() or '' for page in reader.pages
    ).strip()


def _to_decimal(value):
    """Coerce JSON/regex numbers to Decimal; None when missing.

    Spaces and non-breaking spaces are stripped first so
    thousands-separated values like ``'1 234,56'`` survive.
    """
    if value is None or value == '':
        return None
    if isinstance(value, Decimal):
        return value
    cleaned = (
        str(value).strip().replace('\xa0', '').replace(' ', '')
        .replace(',', '.')
    )
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _parse_purchased_at(value):
    """'YYYY-MM-DD HH:MM' (or ISO) → aware datetime, else None."""
    if not value:
        return None
    text = str(value).strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return timezone.make_aware(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def _parse_ai_json(text):
    """json.loads tolerant of markdown fences and junk around the
    JSON object — ``raw_decode`` ignores anything trailing it."""
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```[A-Za-z]*\s*', '', cleaned)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
    start = cleaned.find('{')
    if start > 0:
        cleaned = cleaned[start:]
    return json.JSONDecoder().raw_decode(cleaned)[0]


def _normalize_ai_output(data):
    """Model JSON → the canonical parsed dict (like parse_invoice)."""
    items = []
    for position, raw in enumerate(data.get('items') or [], 1):
        # `is None`, not falsy: a legit quantity of 0 stays 0.
        quantity = _to_decimal(raw.get('quantity'))
        items.append({
            'raw_name': str(raw.get('name') or '')[:300],
            'quantity': (
                quantity if quantity is not None else Decimal(1)
            ),
            'unit': str(raw.get('unit') or '')[:10],
            'unit_price': _to_decimal(raw.get('unit_price')),
            'discount': _to_decimal(raw.get('discount')) or Decimal(0),
            'total': _to_decimal(raw.get('total')) or Decimal(0),
            'vat_class': str(raw.get('vat_class') or '')[:2],
            'vat_rate': None,
            'is_fee': bool(raw.get('is_fee')),
            'position': position,
        })
    store_name = str(data.get('store_name') or '')
    return {
        'chain': 'rimi' if 'rimi' in store_name.lower() else '',
        'store_name': store_name[:200],
        'store_address': str(data.get('store_address') or '')[:300],
        'vat_number': str(data.get('vat_number') or '')[:30],
        'register_number': str(data.get('register_number') or '')[:20],
        'document_number': str(data.get('document_number') or '')[:50],
        'purchased_at': _parse_purchased_at(data.get('purchased_at')),
        'currency': (str(data.get('currency') or 'EUR'))[:3],
        'total': _to_decimal(data.get('total')),
        'total_discount': (
            _to_decimal(data.get('total_discount')) or Decimal(0)
        ),
        'payment_method': str(data.get('payment_method') or '')[:50],
        'items': items,
    }


def _extract_with_ai(client, pdf_bytes, filename):
    """JobClient multimodal path for image-only PDFs (§5.2 step 4).

    The whole PDF goes to Gemini as an inline ImagePart — the same
    path fetcher uses for ``fileDetails`` PDFs, so no
    pdf2image/tesseract/system packages are needed.
    """
    supports = getattr(client, 'supports_json_mode', None)
    json_mode = bool(supports and supports('extract'))
    ai_result = client.generate(
        PromptSpec(
            template_key='receipts.receipt_extract',
            template_text=_load_prompt(),
            input_text=filename or 'receipt.pdf',
            layout='system_v1',
            images=(
                ImagePart(
                    data=pdf_bytes,
                    mime_type='application/pdf',
                ),
            ),
        ),
        role='extract',
        options=GenerationOptions(json_mode=json_mode),
    )
    raw = ai_result.text or ''
    parsed = _normalize_ai_output(_parse_ai_json(raw))
    parsed['raw_text'] = raw
    return parsed


def _filename_doc_numbers(source_filename):
    """'<kase>-<docnr>.pdf' → (kase, docnr), else (None, None)."""
    stem = os.path.splitext(os.path.basename(source_filename or ''))[0]
    match = _FILENAME_DOC_RE.match(stem)
    if match is None:
        return None, None
    return match.group(1), match.group(2)


def reconcile(parsed, source_filename=''):
    """Cross-check a normalized dict before rows are written (§5.4).

    Returns ``'parsed'`` or ``'total_mismatch'`` — mismatches are
    stored, not rejected: a wrong row is better than a lost one, and
    the flag is the quality metric for prompt/parser iteration.
    """
    total = parsed.get('total')
    items = parsed.get('items') or []
    if total is None:
        # Nothing to reconcile against; keep what data exists.
        return Receipt.PARSED
    if not items:
        # A total without an items list is itself a mismatch.
        return Receipt.TOTAL_MISMATCH
    items_sum = sum(
        (item['total'] for item in items), Decimal(0)
    )
    if abs(items_sum - total) > ITEMS_SUM_TOLERANCE:
        return Receipt.TOTAL_MISMATCH
    for item in items:
        unit_price = item.get('unit_price')
        if unit_price is None:
            continue
        discount = item.get('discount') or Decimal(0)
        expected = item['quantity'] * unit_price - discount
        if abs(expected - item['total']) > LINE_TOLERANCE:
            return Receipt.TOTAL_MISMATCH
    # Optional VAT cross-check: items sum + receipt-level discount
    # should equal the summed per-rate 'ar PVN' gross totals.
    vat_totals = parsed.get('vat_totals')
    if vat_totals:
        vat_sum = sum(vat_totals.values(), Decimal(0))
        gross = items_sum + (parsed.get('total_discount') or Decimal(0))
        if abs(gross - vat_sum) > ITEMS_SUM_TOLERANCE:
            return Receipt.TOTAL_MISMATCH
    # Filename cross-check (e-receipts): '<kase>-<docnr>.pdf' must
    # agree with the extracted register/document numbers.
    kase, docnr = _filename_doc_numbers(source_filename)
    register_number = parsed.get('register_number') or ''
    document_number = parsed.get('document_number') or ''
    if kase and register_number and kase != register_number:
        return Receipt.TOTAL_MISMATCH
    if docnr and document_number and docnr not in document_number:
        return Receipt.TOTAL_MISMATCH
    return Receipt.PARSED


def _parse_pdf(pdf_bytes, filename, get_ai_client, dry_run):
    """Route one PDF through text-layer or AI extraction.

    Returns the normalized dict, or None for a dry-run over an
    image-only PDF (no paid call). Raises on parse failure — the
    caller records a ``parse_error`` row.
    """
    text = _extract_pdf_text(pdf_bytes)
    if text:
        parsed = parse_invoice_text(text)
        parsed['raw_text'] = text
        return parsed
    if dry_run:
        logger.info(
            '[dry-run] %s has no text layer — would call '
            'receipts.receipt_extract', filename)
        return None
    client = get_ai_client() if get_ai_client else None
    if client is None:
        raise RuntimeError(
            f'{filename}: image-only PDF but no AI client available'
        )
    return _extract_with_ai(client, pdf_bytes, filename)


def _match_product(raw_name):
    """Link an existing canonical Product by name, if one exists."""
    if not raw_name:
        return None
    return Product.objects.filter(name__iexact=raw_name).first()


def _write_receipt(user, parsed, sha, filename, message_id, status):
    """Receipt + ReceiptItem rows; runs inside the caller's
    transaction.atomic() block. Raises IntegrityError on the
    (user, source_ref) unique key — already imported."""
    store = None
    if parsed.get('store_name'):
        store, _ = Store.objects.get_or_create(
            chain=parsed.get('chain') or 'unknown',
            name=parsed['store_name'],
            defaults={
                'address': parsed.get('store_address') or '',
                'vat_number': parsed.get('vat_number') or '',
            },
        )
    receipt = Receipt.objects.create(
        user=user,
        store=store,
        purchased_at=parsed.get('purchased_at'),
        document_number=parsed.get('document_number') or '',
        register_number=parsed.get('register_number') or '',
        total=parsed.get('total'),
        currency=parsed.get('currency') or 'EUR',
        payment_method=parsed.get('payment_method') or '',
        total_discount=parsed.get('total_discount') or 0,
        source_ref=sha,
        # max_length=255 — Postgres raises DataError on longer
        # names, which would leave the message UNSEEN and retry
        # (re-paying the AI call) forever.
        source_filename=(filename or '')[:255],
        message_id=(message_id or '')[:255],
        raw_text=parsed.get('raw_text') or '',
        parse_status=status,
    )
    for item in parsed.get('items') or []:
        ReceiptItem.objects.create(
            receipt=receipt,
            product=_match_product(item['raw_name']),
            raw_name=item['raw_name'],
            quantity=item['quantity'],
            unit=item.get('unit') or '',
            unit_price=item.get('unit_price'),
            discount=item.get('discount') or 0,
            total=item['total'],
            vat_class=item.get('vat_class') or '',
            vat_rate=item.get('vat_rate'),
            is_fee=bool(item.get('is_fee')),
            position=item['position'],
        )
    return receipt


def _write_parse_error(user, sha, filename, message_id, tb):
    """Record a parse_error row — keeps source_ref so a fix can
    re-process the PDF from Gmail manually (§5.2 step 7)."""
    try:
        Receipt.objects.create(
            user=user,
            source_ref=sha,
            source_filename=(filename or '')[:255],
            message_id=(message_id or '')[:255],
            parse_status=Receipt.PARSE_ERROR,
            parse_error=tb[:4000],
        )
    except IntegrityError:
        logger.warning(
            'parse_error row already exists for %s', sha[:12])


def _rule_matches(rule, lowered_name):
    pattern = rule.pattern.lower()
    if rule.match_type == CategoryRule.EQUALS:
        return lowered_name == pattern
    if rule.match_type == CategoryRule.STARTS_WITH:
        return lowered_name.startswith(pattern)
    if rule.match_type == CategoryRule.ENDS_WITH:
        return lowered_name.endswith(pattern)
    return pattern in lowered_name   # default: contains


def apply_category_rules(user, receipt):
    """Per-user CategoryRule pass over raw_name (§5.2 step 8).

    Rules are applied case-insensitively, ordered (priority, pk);
    the first matching rule wins. Failures are logged, never
    propagated — categorization must not roll back a stored
    receipt.
    """
    rules = list(
        CategoryRule.objects
        .filter(user=user, is_active=True)
        .select_related('category')
        .order_by('priority', 'pk')
    )
    if not rules:
        return
    for item in receipt.items.filter(category__isnull=True):
        lowered = item.raw_name.lower()
        for rule in rules:
            if _rule_matches(rule, lowered):
                item.category = rule.category
                item.save(update_fields=['category'])
                break


def _enrich_from_filename(parsed, filename):
    """Fill register/document numbers from '<kase>-<docnr>.pdf'
    when the parser did not produce them (free signal)."""
    kase, docnr = _filename_doc_numbers(filename)
    if kase and not parsed.get('register_number'):
        parsed['register_number'] = kase
    if docnr and not parsed.get('document_number'):
        parsed['document_number'] = docnr


def _process_attachment(user, pdf_bytes, filename, message_id,
                        get_ai_client, dry_run, result):
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    if Receipt.objects.filter(user=user, source_ref=sha).exists():
        result.skipped += 1
        return
    try:
        parsed = _parse_pdf(pdf_bytes, filename, get_ai_client, dry_run)
        if parsed is None:
            result.ai_pending += 1     # dry-run over an image PDF
            return
        _enrich_from_filename(parsed, filename)
        status = reconcile(parsed, source_filename=filename)
        if dry_run:
            logger.info(
                '[dry-run] would store receipt %s status=%s '
                'items=%d total=%s',
                filename, status, len(parsed.get('items') or []),
                parsed.get('total'),
            )
            result.created += 1
            return
        try:
            with transaction.atomic():
                receipt = _write_receipt(
                    user, parsed, sha, filename, message_id, status)
        except IntegrityError:
            # Expected source: the unique (user, source_ref) race
            # — already imported by a concurrent run. Any other
            # IntegrityError inside the atomic block (e.g. the
            # Store get_or_create unique_together race) must NOT
            # be counted as "imported", or the message would be
            # marked \Seen with no row written.
            if not Receipt.objects.filter(
                    user=user, source_ref=sha).exists():
                raise
            result.skipped += 1
            return
        try:
            apply_category_rules(user, receipt)
        except Exception:
            logger.warning(
                'category pass failed for receipt %s', receipt.pk,
                exc_info=True)
        result.created += 1
    except AIJobError:
        # Transient/cap/config failure (request cap, all models
        # failed, job unseeded/disabled): propagate so the command
        # aborts the run and leaves the message UNSEEN for retry —
        # a parse_error row + \Seen would poison it via sha256
        # dedup.
        raise
    except Exception:
        tb = traceback.format_exc()
        logger.error(
            'receipt parse failed for %s:\n%s', filename, tb)
        if not dry_run:
            _write_parse_error(user, sha, filename, message_id, tb)
        result.errors += 1


def process_message(user, email_msg, get_ai_client=None, dry_run=False):
    """Process one parsed email: extract every PDF attachment.

    ``get_ai_client`` is a zero-arg callable used lazily so the
    AIJob row is only created when an image-only PDF actually needs
    it. Returns ``MessageResult``. Raises ``AIJobError``
    (cap/outage/config — the caller aborts the run and leaves the
    message UNSEEN) or any per-message failure that could not be
    recorded (also left UNSEEN for retry).
    """
    result = MessageResult()
    message_id = (email_msg.get('Message-ID') or '')[:255]
    for filename, pdf_bytes in iter_pdf_attachments(email_msg):
        _process_attachment(
            user, pdf_bytes, filename, message_id,
            get_ai_client, dry_run, result,
        )
    return result
