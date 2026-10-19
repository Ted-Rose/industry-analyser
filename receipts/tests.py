"""Receipts pipeline tests (plan §9) — stub IMAP + stub AI client."""

import hashlib
import imaplib
import json
from decimal import Decimal
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from ai_providers.errors import AIJobError, AIRequestCapReached

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
)
from receipts.parse_invoice import parse_invoice_text

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
    """Duck-typed JobClient stand-in returning canned JSON."""

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
