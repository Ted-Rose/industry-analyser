"""Receipts pipeline tests (plan §9) — stub IMAP + stub AI client."""

import hashlib
import imaplib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ai_providers.errors import (
    AIAllModelsFailedError,
    AIBadRequestError,
    AIJobError,
    AIRequestCapReached,
    AIServerError,
)

from receipts.imap_client import connect, iter_messages, mark_seen
from receipts.ingest import (
    _normalize_ai_output,
    _parse_ai_json,
    apply_category_rules,
    process_message,
    reconcile,
)
from receipts.models import (
    Category,
    CategoryRule,
    Receipt,
    ReceiptItem,
    Store,
)
from receipts.parse_invoice import parse_invoice_text
from receipts.views import _default_range

INVOICE_TEXT = """\
RIMI LATVIJA, SIA
A. Deglava iela 160, Rīga, LV-1021
PVN reģ. nr. LV40003222184

Rēķins Nr. 1234567
Datums: 15.02.2026 14:32
Maksājuma veids: Bankas karte

Nosaukums                            Daudz.  Cena   Summa
Piens Baltais 2,5% 1L                2 gab   1,09   2,18
Banāni                               0,542 kg 1,49  0,81
Piegādes maksa                       1 gab   2,99   2,99

Kopā bez PVN                                4,94
PVN 21%                                     1,04
Kopā                                        5,98
"""

AI_RECEIPT_PAYLOAD = {
    'store_name': 'Rimi Akropolis',
    'store_address': 'A. Deglava iela 160',
    'vat_number': 'LV40003222184',
    'register_number': '2',
    'document_number': '2-999888',
    'purchased_at': '2026-02-15 14:32',
    'currency': 'EUR',
    'total': '5.98',
    'total_discount': '0.00',
    'payment_method': 'card',
    'items': [
        {
            'name': 'Piens Baltais 2,5% 1L',
            'quantity': 2, 'unit': 'gab',
            'unit_price': '1.09', 'discount': '0',
            'total': '2.18', 'vat_class': 'A', 'is_fee': False,
        },
        {
            'name': 'Banāni',
            'quantity': '0.542', 'unit': 'kg',
            'unit_price': '1.49', 'discount': '0',
            'total': '0.81', 'vat_class': 'A', 'is_fee': False,
        },
        {
            'name': 'Piegādes maksa',
            'quantity': 1, 'unit': 'gab',
            'unit_price': '2.99', 'discount': '0',
            'total': '2.99', 'vat_class': '', 'is_fee': True,
        },
    ],
}

FAKE_PDF = b'%PDF-1.4 fake bytes'


def _build_eml(pdf_bytes=FAKE_PDF, filename='invoice123.pdf',
               message_id='<m1@example.com>'):
    msg = EmailMessage()
    msg['From'] = 'me@example.com'
    msg['To'] = 'collector@example.com'
    msg['Subject'] = 'Fwd: Tavs pirkuma čeks'
    msg['Message-ID'] = message_id
    msg.set_content('forwarded receipt')
    if pdf_bytes is not None:
        msg.add_attachment(
            pdf_bytes, maintype='application', subtype='pdf',
            filename=filename,
        )
    return msg.as_bytes()


def _parse_eml(raw):
    return BytesParser(policy=policy.default).parsebytes(raw)


class FakeImap:
    """Stub IMAP handle: search returns all messages as UNSEEN,
    fetch serves raw bytes, store records \\Seen flags."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.seen = []
        self.fetches = []

    def search(self, charset, criteria):
        nums = b' '.join(
            str(i + 1).encode() for i in range(len(self.messages))
        )
        return 'OK', [nums]

    def fetch(self, num, query):
        self.fetches.append(num)
        return 'OK', [(num, self.messages[int(num) - 1])]

    def store(self, num, flags, value):
        self.seen.append((num, flags, value))
        return 'OK', [num]


class FlakyFetchImap(FakeImap):
    """fetch() returns a non-OK status for ``fail_nums`` and
    raises an IMAP abort for ``raise_nums``; successful fetches
    also carry a non-tuple part like real imaplib responses."""

    def __init__(self, messages, fail_nums=(), raise_nums=()):
        super().__init__(messages)
        self.fail_nums = {str(n).encode() for n in fail_nums}
        self.raise_nums = {str(n).encode() for n in raise_nums}

    def fetch(self, num, query):
        self.fetches.append(num)
        if num in self.raise_nums:
            raise imaplib.IMAP4.abort('connection dropped')
        if num in self.fail_nums:
            return 'NO', None
        return 'OK', [
            b'FLAGS (\\Seen)',   # non-tuple part must be skipped
            (num, self.messages[int(num) - 1]),
        ]


class _StubAIResult:
    def __init__(self, text):
        self.text = text


class StubAIClient:
    """Duck-typed JobClient stand-in returning canned JSON.

    ``_assignments`` mirrors JobClient's construction-time
    snapshot: one active 'extract' assignment, so a raised
    AIAllModelsFailedError's last_error is the whole story and
    can still downgrade to parse_error.
    """

    _assignments = {'extract': [object()]}

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def supports_json_mode(self, role):
        return True

    def generate(self, spec, role, options=None):
        self.calls.append((spec, role, options))
        return _StubAIResult(json.dumps(self.payload))


def _parsed_dict(**overrides):
    parsed = {
        'chain': 'rimi',
        'store_name': 'Rimi',
        'total': Decimal('5.98'),
        'total_discount': Decimal(0),
        'register_number': '2',
        'document_number': '2-999888',
        'fb_number': '',
        'items': [
            {
                'raw_name': 'Piens', 'quantity': Decimal(2),
                'unit': 'gab', 'unit_price': Decimal('1.09'),
                'discount': Decimal(0), 'total': Decimal('2.18'),
                'vat_class': '', 'vat_rate': None,
                'is_fee': False, 'position': 1,
            },
            {
                'raw_name': 'Banāni', 'quantity': Decimal('0.542'),
                'unit': 'kg', 'unit_price': Decimal('1.49'),
                'discount': Decimal(0), 'total': Decimal('0.81'),
                'vat_class': '', 'vat_rate': None,
                'is_fee': False, 'position': 2,
            },
            {
                'raw_name': 'Piegādes maksa',
                'quantity': Decimal(1), 'unit': 'gab',
                'unit_price': Decimal('2.99'),
                'discount': Decimal(0), 'total': Decimal('2.99'),
                'vat_class': '', 'vat_rate': None,
                'is_fee': True, 'position': 3,
            },
        ],
    }
    parsed.update(overrides)
    return parsed


class ParseInvoiceTests(SimpleTestCase):
    """parse_invoice on invoice-shaped pypdf text-layer output."""

    def setUp(self):
        self.parsed = parse_invoice_text(INVOICE_TEXT)

    def test_header_fields(self):
        self.assertEqual(self.parsed['chain'], 'rimi')
        self.assertEqual(self.parsed['store_name'], 'RIMI LATVIJA, SIA')
        self.assertEqual(
            self.parsed['store_address'],
            'A. Deglava iela 160, Rīga, LV-1021',
        )
        self.assertEqual(
            self.parsed['vat_number'], 'LV40003222184')
        self.assertEqual(self.parsed['document_number'], '1234567')
        self.assertEqual(
            self.parsed['payment_method'], 'Bankas karte')
        self.assertEqual(self.parsed['total'], Decimal('5.98'))
        self.assertIsNotNone(self.parsed['purchased_at'])
        self.assertEqual(self.parsed['purchased_at'].hour, 14)

    def test_items(self):
        items = self.parsed['items']
        self.assertEqual(len(items), 3)
        milk, bananas, fee = items
        self.assertEqual(milk['raw_name'], 'Piens Baltais 2,5% 1L')
        self.assertEqual(milk['quantity'], Decimal(2))
        self.assertEqual(milk['unit'], 'gab')
        self.assertEqual(milk['total'], Decimal('2.18'))
        self.assertEqual(bananas['unit'], 'kg')
        self.assertEqual(bananas['quantity'], Decimal('0.542'))
        self.assertTrue(fee['is_fee'])
        self.assertFalse(milk['is_fee'])

    def test_bez_pvn_line_is_not_the_total(self):
        # 'Kopā bez PVN' (4,94) must not shadow 'Kopā' (5,98).
        self.assertEqual(self.parsed['total'], Decimal('5.98'))


class ReconcileTests(SimpleTestCase):
    """reconcile() statuses per §5.4."""

    def test_correct_receipt_is_parsed(self):
        self.assertEqual(
            reconcile(_parsed_dict()), Receipt.PARSED)

    def test_items_sum_mismatch(self):
        parsed = _parsed_dict(total=Decimal('6.50'))
        self.assertEqual(
            reconcile(parsed), Receipt.TOTAL_MISMATCH)

    def test_no_items_with_total_is_mismatch(self):
        parsed = _parsed_dict(items=[])
        self.assertEqual(
            reconcile(parsed), Receipt.TOTAL_MISMATCH)

    def test_missing_total_skips_reconciliation(self):
        parsed = _parsed_dict(total=None)
        self.assertEqual(
            reconcile(parsed), Receipt.PARSED)

    def test_per_item_arithmetic_mismatch(self):
        parsed = _parsed_dict()
        parsed['items'][0]['total'] = Decimal('3.00')
        parsed['total'] = Decimal('6.80')   # keeps the sum check ok
        self.assertEqual(
            reconcile(parsed), Receipt.TOTAL_MISMATCH)

    def test_filename_kase_disagrees(self):
        parsed = _parsed_dict(
            register_number='3', document_number='3-999888')
        self.assertEqual(
            reconcile(parsed, source_filename='2-999888.pdf'),
            Receipt.TOTAL_MISMATCH,
        )

    def test_filename_docnr_disagrees(self):
        parsed = _parsed_dict()
        self.assertEqual(
            reconcile(parsed, source_filename='2-111111.pdf'),
            Receipt.TOTAL_MISMATCH,
        )

    def test_filename_docnr_matches_fb_number(self):
        """docnr is the FB numurs serial — a match there also
        clears the check (real-world: '3642429' vs '#03642429')."""
        parsed = _parsed_dict(
            register_number='36', document_number='171/180789',
            fb_number='03642429')
        self.assertEqual(
            reconcile(parsed, source_filename='36-3642429.pdf'),
            Receipt.PARSED,
        )

    def test_filename_docnr_in_neither_is_mismatch(self):
        parsed = _parsed_dict(
            register_number='36', document_number='171/180789',
            fb_number='0111')
        self.assertEqual(
            reconcile(parsed, source_filename='36-3642429.pdf'),
            Receipt.TOTAL_MISMATCH,
        )

    def test_matching_filename_stays_parsed(self):
        self.assertEqual(
            reconcile(
                _parsed_dict(), source_filename='2-999888.pdf'),
            Receipt.PARSED,
        )

    def test_vat_totals_mismatch(self):
        parsed = _parsed_dict(
            vat_totals={'21': Decimal('1.00')})
        self.assertEqual(
            reconcile(parsed), Receipt.TOTAL_MISMATCH)


class IngestTests(TestCase):
    """End-to-end ingest with stub IMAP + stub AI client."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@x.com')

    def _run_sync(self, raws, get_ai_client=None, dry_run=False):
        """Mirror the command loop: iterate, process, mark \\Seen;
        an AIJobError aborts the run (message stays UNSEEN)."""
        fake = FakeImap(raws)
        results = []
        for num, msg in iter_messages(fake):
            try:
                result = process_message(
                    self.user, msg,
                    get_ai_client=get_ai_client, dry_run=dry_run,
                )
            except AIJobError:
                break
            if not dry_run:
                mark_seen(fake, num)
            results.append(result)
        return fake, results

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_invoice_pdf_creates_rows(self, _extract):
        fake, results = self._run_sync([_build_eml()])
        result = results[0]
        self.assertEqual(result.created, 1)
        self.assertEqual(result.errors, 0)

        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSED)
        self.assertEqual(receipt.total, Decimal('5.98'))
        self.assertEqual(
            receipt.source_ref,
            hashlib.sha256(FAKE_PDF).hexdigest(),
        )
        self.assertEqual(receipt.source_filename, 'invoice123.pdf')
        self.assertEqual(receipt.message_id, '<m1@example.com>')
        self.assertEqual(receipt.store.name, 'RIMI LATVIJA, SIA')
        self.assertEqual(receipt.store.chain, 'rimi')
        self.assertEqual(receipt.items.count(), 3)
        self.assertEqual(receipt.items.get(is_fee=True).total,
                         Decimal('2.99'))
        self.assertEqual(receipt.user, self.user)

        # \Seen stored after successful processing.
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_sha256_dedup_makes_rerun_a_noop(self, _extract):
        raw = _build_eml()
        self._run_sync([raw])
        fake, results = self._run_sync([raw])
        self.assertEqual(results[0].skipped, 1)
        self.assertEqual(results[0].created, 0)
        self.assertEqual(Receipt.objects.count(), 1)
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_message_without_pdf_is_seen_with_no_rows(self, _e):
        raw = _build_eml(pdf_bytes=None)
        fake, results = self._run_sync([raw])
        self.assertEqual(results[0].created, 0)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 1)

    @patch('receipts.ingest._extract_pdf_text')
    def test_parse_failure_writes_parse_error_and_marks_seen(
            self, extract):
        extract.side_effect = ValueError('not a pdf')
        fake, results = self._run_sync([_build_eml()])
        self.assertEqual(results[0].errors, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSE_ERROR)
        self.assertIn('not a pdf', receipt.parse_error)
        self.assertEqual(
            receipt.source_ref,
            hashlib.sha256(FAKE_PDF).hexdigest(),
        )
        self.assertEqual(len(fake.seen), 1)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_image_pdf_uses_ai_path(self, _extract):
        client = StubAIClient(AI_RECEIPT_PAYLOAD)
        raw = _build_eml(filename='2-999888.pdf')
        fake, results = self._run_sync(
            [raw], get_ai_client=lambda: client)
        self.assertEqual(results[0].created, 1)

        spec, role, options = client.calls[0]
        self.assertEqual(role, 'extract')
        self.assertEqual(spec.layout, 'system_v1')
        self.assertEqual(
            spec.images[0].mime_type, 'application/pdf')
        self.assertTrue(options.json_mode)

        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSED)
        self.assertEqual(receipt.document_number, '2-999888')
        self.assertEqual(receipt.register_number, '2')
        self.assertEqual(receipt.items.count(), 3)
        self.assertIn('"store_name"', receipt.raw_text)
        self.assertEqual(len(fake.seen), 1)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_ai_garbage_json_becomes_parse_error(self, _extract):
        client = StubAIClient(None)
        client.generate = lambda *a, **kw: _StubAIResult(
            'sorry, cannot read this')
        fake, results = self._run_sync(
            [_build_eml()], get_ai_client=lambda: client)
        self.assertEqual(results[0].errors, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSE_ERROR)
        self.assertEqual(len(fake.seen), 1)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_ai_cap_reached_leaves_message_unseen(self, _extract):
        """AIRequestCapReached must abort the run: no parse_error
        row, no \\Seen — the message is retried next run instead
        of being poisoned by sha256 dedup."""

        class CapClient(StubAIClient):
            def generate(self, spec, role, options=None):
                raise AIRequestCapReached('per-run cap reached')

        fake, results = self._run_sync(
            [_build_eml(), _build_eml(
                filename='other.pdf',
                message_id='<m2@example.com>')],
            get_ai_client=lambda: CapClient(None),
        )
        # The run aborted on the first message — nothing was
        # processed, written, or marked seen.
        self.assertEqual(results, [])
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 0)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_ai_bad_request_becomes_parse_error(self, _extract):
        """AIAllModelsFailedError whose last_error is a
        deterministic per-document failure (the provider rejects
        the PDF) must not wedge the run: parse_error row + \\Seen
        and the next message is still processed."""

        class BadDocClient(StubAIClient):
            def generate(self, spec, role, options=None):
                raise AIAllModelsFailedError(
                    'all models failed',
                    last_error=AIBadRequestError('PDF too large'),
                )

        other_pdf = b'%PDF-1.4 different bytes'
        fake, results = self._run_sync(
            [
                _build_eml(),
                _build_eml(
                    pdf_bytes=other_pdf, filename='other.pdf',
                    message_id='<m2@example.com>'),
            ],
            get_ai_client=lambda: BadDocClient(None),
        )
        self.assertEqual(results[0].errors, 1)
        self.assertEqual(results[1].errors, 1)  # run continued
        self.assertEqual(
            Receipt.objects.filter(
                parse_status=Receipt.PARSE_ERROR).count(), 2)
        self.assertEqual(len(fake.seen), 2)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_multi_assignment_failure_does_not_downgrade(
            self, _extract):
        """With >=2 active assignments, ``last_error`` is only the
        FINAL model's failure — a deterministic-looking error
        (e.g. m1 timeout + m2 bad-request) must NOT become a
        parse_error that drops a document m1 could parse on
        retry: the run aborts and the mail stays UNSEEN."""

        class MultiClient(StubAIClient):
            _assignments = {'extract': [object(), object()]}

            def generate(self, spec, role, options=None):
                raise AIAllModelsFailedError(
                    'all models failed',
                    last_error=AIBadRequestError('PDF rejected'),
                )

        fake, results = self._run_sync(
            [_build_eml()],
            get_ai_client=lambda: MultiClient(None),
        )
        self.assertEqual(results, [])
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 0)

    def test_empty_pdf_payload_writes_parse_error(self):
        """An empty/undecodable attachment payload must leave a
        parse_error row — not vanish silently while the message
        still gets \\Seen."""
        fake, results = self._run_sync([_build_eml(pdf_bytes=b'')])
        self.assertEqual(results[0].errors, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSE_ERROR)
        self.assertEqual(
            receipt.source_ref, 'empty-invoice123.pdf')
        self.assertIn('empty or undecodable', receipt.parse_error)
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    @patch('receipts.ingest.parse_invoice_text')
    def test_long_document_number_is_truncated(
            self, parse_invoice, _extract):
        """document_number is max_length=50 — an overlong
        parser-supplied value must be truncated at the write path
        instead of raising a Postgres DataError on a parseable
        receipt."""
        parse_invoice.return_value = _parsed_dict(
            document_number='A' * 60)
        fake, results = self._run_sync([_build_eml()])
        self.assertEqual(results[0].created, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.document_number, 'A' * 50)
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    @patch('receipts.ingest.parse_invoice_text')
    def test_long_filename_docnr_is_truncated(
            self, parse_invoice, _extract):
        """'<kase>-<docnr>.pdf' filename enrichment fills fb_number
        (the docnr is the FB numurs serial, not Dok. Nr.) —
        unbounded [A-Za-z0-9]+ truncated to max_length=30."""
        parse_invoice.return_value = _parsed_dict(
            register_number='', document_number='')
        docnr = 'B' * 60
        fake, results = self._run_sync(
            [_build_eml(filename=f'2-{docnr}.pdf')])
        self.assertEqual(results[0].created, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.fb_number, docnr[:30])
        self.assertEqual(receipt.document_number, '')
        self.assertEqual(receipt.register_number, '2')

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_ai_retryable_all_models_failed_aborts_unseen(
            self, _extract):
        """AIAllModelsFailedError with a retryable last_error
        stays an abort: no parse_error row, no \\Seen."""

        class DownClient(StubAIClient):
            def generate(self, spec, role, options=None):
                raise AIAllModelsFailedError(
                    'all models failed',
                    last_error=AIServerError('503'),
                )

        fake, results = self._run_sync(
            [_build_eml(), _build_eml(
                filename='other.pdf',
                message_id='<m2@example.com>')],
            get_ai_client=lambda: DownClient(None),
        )
        self.assertEqual(results, [])
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 0)

    @patch('receipts.ingest._write_receipt')
    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_non_dedup_integrity_error_writes_parse_error(
            self, _extract, write):
        """An IntegrityError that is NOT the (user, source_ref)
        dedup race — no row exists — must become a parse_error
        row, not a dedup-skip."""
        write.side_effect = IntegrityError('store unique race')
        fake, results = self._run_sync([_build_eml()])
        self.assertEqual(results[0].errors, 1)
        self.assertEqual(results[0].skipped, 0)
        receipt = Receipt.objects.get()
        self.assertEqual(receipt.parse_status, Receipt.PARSE_ERROR)
        self.assertIn('store unique race', receipt.parse_error)
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_long_filename_is_truncated(self, _extract):
        long_name = 'a' * 300 + '.pdf'
        fake, results = self._run_sync(
            [_build_eml(filename=long_name)])
        self.assertEqual(results[0].created, 1)
        receipt = Receipt.objects.get()
        self.assertEqual(len(receipt.source_filename), 255)
        self.assertEqual(receipt.source_filename, long_name[:255])
        self.assertEqual(len(fake.seen), 1)

    @patch(
        'receipts.ingest._extract_pdf_text',
        return_value=INVOICE_TEXT)
    def test_dry_run_writes_nothing(self, _extract):
        fake, results = self._run_sync([_build_eml()], dry_run=True)
        self.assertEqual(results[0].created, 1)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 0)

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_dry_run_image_pdf_counts_ai_pending(self, _extract):
        fake, results = self._run_sync([_build_eml()], dry_run=True)
        self.assertEqual(results[0].ai_pending, 1)
        self.assertEqual(Receipt.objects.count(), 0)


class ImapClientTests(SimpleTestCase):
    """connect() settings guard + iter_messages resilience."""

    @override_settings(
        RECEIPTS_IMAP_USER='', RECEIPTS_IMAP_PASSWORD='')
    def test_connect_empty_settings_raises_value_error(self):
        with self.assertRaises(ValueError):
            connect()

    @override_settings(
        RECEIPTS_IMAP_USER='u@x.com', RECEIPTS_IMAP_PASSWORD='')
    def test_connect_empty_password_raises_value_error(self):
        with self.assertRaises(ValueError):
            connect()

    def test_failed_fetch_is_skipped(self):
        fake = FlakyFetchImap(
            [_build_eml(), _build_eml(), _build_eml()],
            fail_nums={1},
        )
        pairs = list(iter_messages(fake))
        self.assertEqual(len(pairs), 2)
        self.assertEqual(
            [num for num, _msg in pairs], [b'2', b'3'])

    def test_fetch_abort_is_skipped(self):
        fake = FlakyFetchImap(
            [_build_eml(), _build_eml()],
            raise_nums={1},
        )
        pairs = list(iter_messages(fake))
        self.assertEqual(len(pairs), 1)

    def test_limit_avoids_extra_body_fetch(self):
        fake = FakeImap([_build_eml(), _build_eml(), _build_eml()])
        pairs = list(iter_messages(fake, limit=2))
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len(fake.fetches), 2)

    def test_non_ok_search_raises(self):
        """A refused search (NO/BAD) is a broken mailbox — it must
        raise so the command exits non-zero, not silently report
        an empty inbox."""

        class BadSearchImap(FakeImap):
            def search(self, charset, criteria):
                return 'NO', [b'[CANNOT] mailbox broken']

        with self.assertRaises(imaplib.IMAP4.error):
            list(iter_messages(BadSearchImap([_build_eml()])))

    def test_empty_inbox_returns_no_messages(self):
        class EmptyImap(FakeImap):
            def search(self, charset, criteria):
                return 'OK', [b'']

        self.assertEqual(list(iter_messages(EmptyImap([]))), [])


class SyncReceiptEmailsCommandTests(TestCase):
    """call_command-level coverage for sync_receipt_emails — the
    real handle() loop, with only IMAP and the AI client stubbed.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@x.com')

    @patch('receipts.ingest._extract_pdf_text', return_value='')
    def test_ai_job_error_aborts_run_unseen(self, _extract):
        """An AIJobError (provider outage here) must propagate
        through the real command loop: CommandError → non-zero
        exit, and the message is left UNSEEN for the next run."""
        fake = FakeImap([_build_eml()])

        class DownClient(StubAIClient):
            def generate(self, spec, role, options=None):
                raise AIAllModelsFailedError(
                    'all models failed',
                    last_error=AIServerError('503'),
                )

        command_module = (
            'receipts.management.commands.sync_receipt_emails'
        )
        with patch(
            f'{command_module}.connect', return_value=fake,
        ), patch(
            f'{command_module}.get_job_client',
            return_value=DownClient(None),
        ):
            with self.assertRaises(CommandError):
                call_command('sync_receipt_emails')

        # The fetch happened (the real iter_messages ran), but no
        # row was written and no \Seen was stored.
        self.assertEqual(len(fake.fetches), 1)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(len(fake.seen), 0)


class NormalizeAiOutputTests(SimpleTestCase):
    """_normalize_ai_output/_to_decimal/_parse_ai_json nits."""

    def test_quantity_zero_is_not_replaced_by_one(self):
        parsed = _normalize_ai_output({
            'items': [{
                'name': 'Free sample', 'quantity': 0,
                'unit_price': '0.00', 'total': '0.00',
            }],
        })
        self.assertEqual(
            parsed['items'][0]['quantity'], Decimal(0))

    def test_spaced_thousands_decimal(self):
        parsed = _normalize_ai_output({'total': '1 234,56'})
        self.assertEqual(parsed['total'], Decimal('1234.56'))

    def test_parse_ai_json_tolerates_trailing_junk(self):
        self.assertEqual(
            _parse_ai_json('{"a": 1} some trailing note'),
            {'a': 1})

    def test_repeated_discount_line_is_deduped(self):
        text = (
            INVOICE_TEXT
            + 'Atlaide: 0,50\n'
            + 'Atlaide: 0,50\n'
            + 'Ietaupījums: 0,30\n'
        )
        parsed = parse_invoice_text(text)
        self.assertEqual(
            parsed['total_discount'], Decimal('0.80'))

    def test_same_amount_different_discount_lines_both_count(self):
        text = (
            INVOICE_TEXT
            + 'Atlaide: 0,50\n'
            + 'Kartes atlaide: 0,50\n'
        )
        parsed = parse_invoice_text(text)
        self.assertEqual(
            parsed['total_discount'], Decimal('1.00'))


class CategoryRuleTests(TestCase):
    """CategoryRule first-match ordering (priority, pk)."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@x.com')
        self.receipt = Receipt.objects.create(
            user=self.user, source_ref='x' * 64,
            total=Decimal('1.00'))
        self.item = ReceiptItem.objects.create(
            receipt=self.receipt, raw_name='Banāni',
            quantity=Decimal(1), total=Decimal('1.00'), position=1)

    def test_lower_priority_number_wins(self):
        fruit = Category.objects.create(
            user=self.user, name='Augļi')
        other = Category.objects.create(
            user=self.user, name='Cits')
        CategoryRule.objects.create(
            user=self.user, category=other, pattern='ban',
            priority=5)
        CategoryRule.objects.create(
            user=self.user, category=fruit, pattern='banāni',
            priority=1)
        apply_category_rules(self.user, self.receipt)
        self.item.refresh_from_db()
        self.assertEqual(self.item.category, fruit)

    def test_same_priority_first_pk_wins(self):
        cat_a = Category.objects.create(user=self.user, name='A')
        cat_b = Category.objects.create(user=self.user, name='B')
        first = CategoryRule.objects.create(
            user=self.user, category=cat_a, pattern='banāni',
            match_type=CategoryRule.STARTS_WITH)
        CategoryRule.objects.create(
            user=self.user, category=cat_b, pattern='ban',
            match_type=CategoryRule.CONTAINS)
        apply_category_rules(self.user, self.receipt)
        self.item.refresh_from_db()
        self.assertEqual(self.item.category, cat_a)
        self.assertTrue(first.pk)

    def test_inactive_rule_is_skipped(self):
        cat = Category.objects.create(user=self.user, name='X')
        CategoryRule.objects.create(
            user=self.user, category=cat, pattern='banāni',
            is_active=False)
        apply_category_rules(self.user, self.receipt)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.category)


class DashboardViewTests(TestCase):
    """GET /receipts/ — the admin-hardcoded spending dashboard."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@x.com')
        self.store = Store.objects.create(
            chain='rimi', name='Rimi Akropolis')
        self.receipt = Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.now(),
            document_number='2-999888',
            total=Decimal('5.98'), source_ref='a' * 64)
        ReceiptItem.objects.create(
            receipt=self.receipt, raw_name='Piens',
            quantity=Decimal(1), unit='gab',
            unit_price=Decimal('5.98'), total=Decimal('5.98'),
            position=1)

    def test_dashboard_200_shows_receipt_data(self):
        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Rimi Akropolis')
        self.assertContains(resp, '2-999888')
        self.assertContains(resp, '5.98')
        self.assertContains(resp, 'Piens')

    def test_dashboard_only_shows_admin_receipts(self):
        other = get_user_model().objects.create_user(
            username='other', password='x')
        Receipt.objects.create(
            user=other, document_number='OTHER-DOC',
            total=Decimal('99.00'), source_ref='b' * 64)
        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'OTHER-DOC')

    def test_dashboard_no_admin_user_renders_no_data(self):
        self.user.delete()   # cascades to the receipt
        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No data')

    def test_aggregates_not_inflated_by_item_join(self):
        """Regression: the item_count annotation's items join must
        not leak into the aggregates — a receipt with N items was
        counted N times (Count('pk')=N, Sum('total')=total*N)."""
        self.receipt.delete()
        receipt = Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.now(),
            document_number='9-111222',
            total=Decimal('42.08'), source_ref='c' * 64)
        for position, amount in enumerate(
                ('20.00', '15.08', '7.00'), start=1):
            ReceiptItem.objects.create(
                receipt=receipt, raw_name=f'Item {position}',
                quantity=Decimal(1), unit='gab',
                unit_price=Decimal(amount),
                total=Decimal(amount), position=position)

        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertEqual(resp.status_code, 200)

        monthly = list(resp.context['monthly'])
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly[0]['receipt_count'], 1)
        self.assertEqual(monthly[0]['total'], Decimal('42.08'))

        by_store = list(resp.context['by_store'])
        self.assertEqual(len(by_store), 1)
        self.assertEqual(by_store[0]['receipt_count'], 1)
        self.assertEqual(by_store[0]['total'], Decimal('42.08'))

        self.assertEqual(resp.context['summary'], {
            'total_spend': Decimal('42.08'), 'receipt_count': 1})
        self.assertEqual(resp.context['item_count'], 3)

    def test_date_range_filter_narrows_results(self):
        """Receipts outside ?date_from..?date_to drop out of
        summary, monthly, by_store, categories and the table."""
        out = Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.make_aware(
                datetime(2020, 1, 5, 12)),
            document_number='OUT-1', total=Decimal('99.00'),
            source_ref='d' * 64)
        ReceiptItem.objects.create(
            receipt=out, raw_name='OldItem', quantity=Decimal(1),
            unit='gab', unit_price=Decimal('99.00'),
            total=Decimal('99.00'), position=1)

        today = timezone.localdate()
        resp = self.client.get(reverse('receipts:dashboard'), {
            'date_from': (today - timedelta(days=30)).isoformat(),
            'date_to': today.isoformat(),
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '2-999888')
        self.assertNotContains(resp, 'OUT-1')
        self.assertNotContains(resp, 'OldItem')
        self.assertEqual(resp.context['summary'], {
            'total_spend': Decimal('5.98'), 'receipt_count': 1})
        self.assertEqual(len(list(resp.context['monthly'])), 1)
        self.assertEqual(len(list(resp.context['receipts'])), 1)
        self.assertEqual(resp.context['item_count'], 1)

    def test_default_range_covers_last_12_months(self):
        """No params: an 11-month-old receipt is in, a
        13-month-old one is out."""
        Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.now() - timedelta(days=335),
            document_number='IN-11M', total=Decimal('10.00'),
            source_ref='e' * 64)
        Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.now() - timedelta(days=400),
            document_number='OUT-13M', total=Decimal('10.00'),
            source_ref='f' * 64)

        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'IN-11M')
        self.assertNotContains(resp, 'OUT-13M')

    def test_invalid_date_params_fall_back_to_defaults(self):
        resp = self.client.get(reverse('receipts:dashboard'), {
            'date_from': 'not-a-date', 'date_to': '2026-13-99'})
        self.assertEqual(resp.status_code, 200)
        def_from, def_to = _default_range(timezone.localdate())
        self.assertEqual(resp.context['date_from'], def_from)
        self.assertEqual(resp.context['date_to'], def_to)
        self.assertContains(resp, '2-999888')

    def test_category_spend_groups_averages_and_top_items(self):
        """Items aggregate per category; uncategorized items land
        in their own bucket; monthly_avg = total / calendar
        months covered by the range (Jan–Feb here = 2)."""
        self.receipt.delete()   # 'Piens' is uncategorized noise
        fruit = Category.objects.create(
            user=self.user, name='Augļi')
        bread = Category.objects.create(
            user=self.user, name='Maize')
        receipt = Receipt.objects.create(
            user=self.user, store=self.store,
            purchased_at=timezone.make_aware(
                datetime(2026, 1, 15, 12)),
            document_number='CAT-1', total=Decimal('30.00'),
            source_ref='9' * 64)
        rows = [
            ('Banāni', '10.00', fruit),
            ('Āboli', '8.00', fruit),
            ('Rudzu maize', '7.00', bread),
            ('Mystery', '5.00', None),
        ]
        for pos, (name, total, cat) in enumerate(rows, start=1):
            ReceiptItem.objects.create(
                receipt=receipt, raw_name=name, category=cat,
                quantity=Decimal(1), unit='gab',
                unit_price=Decimal(total), total=Decimal(total),
                position=pos)

        resp = self.client.get(reverse('receipts:dashboard'), {
            'date_from': '2026-01-01', 'date_to': '2026-02-28'})
        self.assertEqual(resp.status_code, 200)

        cats = resp.context['categories']
        self.assertEqual(
            [c['name'] for c in cats],
            ['Augļi', 'Maize', 'Uncategorized'])
        self.assertEqual(cats[0]['total'], Decimal('18.00'))
        self.assertEqual(cats[0]['item_count'], 2)
        self.assertEqual(cats[0]['monthly_avg'], Decimal('9.00'))
        self.assertEqual(cats[1]['monthly_avg'], Decimal('3.50'))
        self.assertEqual(cats[2]['monthly_avg'], Decimal('2.50'))
        self.assertEqual(
            [i['raw_name'] for i in cats[0]['top_items']],
            ['Banāni', 'Āboli'])

    def test_category_rows_render_collapsible_details(self):
        cat = Category.objects.create(
            user=self.user, name='Augļi')
        ReceiptItem.objects.create(
            receipt=self.receipt, raw_name='Banāni', category=cat,
            quantity=Decimal(1), unit='gab',
            unit_price=Decimal('1.00'), total=Decimal('1.00'),
            position=2)
        resp = self.client.get(reverse('receipts:dashboard'))
        self.assertContains(resp, '<details class="cat">')
        self.assertContains(resp, 'Augļi')
        self.assertContains(resp, 'Banāni')


class SeedCategoriesCommandTests(TestCase):
    """seed_categories: idempotent taxonomy seed + reapply pass."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@x.com')
        self.receipt = Receipt.objects.create(
            user=self.user, source_ref='seed' + '0' * 60,
            total=Decimal('1.00'))

    def _item(self, name, position):
        return ReceiptItem.objects.create(
            receipt=self.receipt, raw_name=name,
            quantity=Decimal(1), unit='gab',
            total=Decimal('1.00'), position=position)

    def test_seeds_categories_rules_and_applies(self):
        self._item('Pilnpiena biezpiens Rimi, 9%', 1)
        self._item('Zobu pasta Parodontax Classic 75ml', 2)
        self._item('Žurnāls Sudoku SMS', 3)
        self._item('Rudzu maize sagriezta 1kg', 4)

        call_command('seed_categories', '--user', 'admin')

        from receipts.management.commands.seed_categories import (
            SEED_CATEGORIES,
        )
        self.assertEqual(
            Category.objects.filter(user=self.user).count(),
            len(SEED_CATEGORIES))
        self.assertGreater(
            CategoryRule.objects.filter(user=self.user).count(), 0)

        items = {
            i.raw_name: i.category.name
            for i in ReceiptItem.objects.all()
        }
        # 'biezpiens' must beat the generic 'piens' shadowed rule.
        self.assertEqual(
            items['Pilnpiena biezpiens Rimi, 9%'],
            'Piena produkti')
        self.assertEqual(
            items['Zobu pasta Parodontax Classic 75ml'], 'Higiēna')
        self.assertEqual(items['Žurnāls Sudoku SMS'], 'Preses')
        self.assertEqual(items['Rudzu maize sagriezta 1kg'], 'Maize')

    def test_rerun_is_idempotent(self):
        call_command('seed_categories', '--user', 'admin')
        cats = Category.objects.count()
        rules = CategoryRule.objects.count()
        call_command('seed_categories', '--user', 'admin')
        self.assertEqual(Category.objects.count(), cats)
        self.assertEqual(CategoryRule.objects.count(), rules)

    def test_dry_run_writes_nothing(self):
        self._item('Zobu pasta Parodontax Classic 75ml', 1)
        call_command('seed_categories', '--user', 'admin',
                     '--dry-run')
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(CategoryRule.objects.count(), 0)
        self.assertIsNone(
            ReceiptItem.objects.get().category)

    def test_meat_split_and_sausages_as_toppings(self):
        """Specific meats land in their own categories; sausages
        count as sandwich toppings; 'cūkgaļa' beats 'gaļa'."""
        self._item('Vistas fileja bez ādas 1kg', 1)
        self._item('Cūkgaļas karbonāde 500g', 2)
        self._item('Liellopa antrekots 400g', 3)
        self._item('Maltā gaļa MIX 400g', 4)
        self._item('Desa Jelgava jubilejas 280g', 5)
        self._item('Cīsiņi grila 300g', 6)

        call_command('seed_categories', '--user', 'admin')

        items = {
            i.raw_name: i.category.name
            for i in ReceiptItem.objects.all()
        }
        self.assertEqual(
            items['Vistas fileja bez ādas 1kg'], 'Vistas gaļa')
        self.assertEqual(
            items['Cūkgaļas karbonāde 500g'], 'Cūkgaļa')
        self.assertEqual(
            items['Liellopa antrekots 400g'], 'Liellopu gaļa')
        self.assertEqual(items['Maltā gaļa MIX 400g'], 'Gaļa')
        self.assertEqual(
            items['Desa Jelgava jubilejas 280g'],
            'Sendviču piedevas')
        self.assertEqual(
            items['Cīsiņi grila 300g'], 'Sendviču piedevas')

    def test_obsolete_rules_are_deleted(self):
        galya = Category.objects.create(
            user=self.user, name='Gaļa')
        stale = CategoryRule.objects.create(
            user=self.user, category=galya, pattern='desa',
            match_type=CategoryRule.CONTAINS, priority=50)
        call_command('seed_categories', '--user', 'admin')
        self.assertFalse(
            CategoryRule.objects.filter(pk=stale.pk).exists())

    def test_reapply_recategorizes_all_items(self):
        self._item('Desa Jelgava jubilejas 280g', 1)
        old = Category.objects.create(user=self.user, name='Gaļa')
        ReceiptItem.objects.update(category=old)

        call_command('seed_categories', '--user', 'admin')
        self.assertEqual(
            ReceiptItem.objects.get().category.name, 'Gaļa')

        call_command(
            'seed_categories', '--user', 'admin', '--reapply')
        self.assertEqual(
            ReceiptItem.objects.get().category.name,
            'Sendviču piedevas')
