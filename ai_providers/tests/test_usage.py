"""Tests for ai_providers.usage, the admin usage view/columns and
the prune_ai_requests command (PR-8)."""

import datetime
import hashlib
import io
from decimal import Decimal

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, models
from django.test import (
    RequestFactory,
    TestCase,
    TransactionTestCase,
)
from django.urls import reverse
from django.utils import timezone

from ai_providers import usage
from ai_providers.admin import AIJobAdmin, AIModelAdmin
from ai_providers.management.commands.prune_ai_requests import (
    referenced_request_pks,
)
from ai_providers.models import (
    AIInput,
    AIJob,
    AIModel,
    AIProvider,
    AIRequest,
)


class FakeAnalysis(models.Model):
    """Test-only FK consumer of AIRequest, standing in for
    blogs.PageAnalysis.ai_request (PR-6) so prune introspection of
    ``AIRequest._meta.related_objects`` can be exercised without
    importing blogs."""

    ai_request = models.ForeignKey(
        'ai_providers.AIRequest',
        on_delete=models.PROTECT,
        null=True,
        related_name='fake_analyses',
    )

    class Meta:
        app_label = 'ai_providers'
        db_table = 'ai_request_fake_analysis'


def make_provider(**kwargs):
    defaults = {
        'slug': 'gemini',
        'display_name': 'Google Gemini',
        'provider_type': 'gemini',
        'api_key_setting': 'GEMINI_API_KEY',
    }
    defaults.update(kwargs)
    return AIProvider.objects.create(**defaults)


def make_model(provider, **kwargs):
    defaults = {'provider': provider, 'name': 'gemini-2.5-pro'}
    defaults.update(kwargs)
    return AIModel.objects.create(**defaults)


def make_job(**kwargs):
    defaults = {
        'slug': 'blogs.theme_analysis',
        'declared_roles': ['cheap', 'expensive'],
    }
    defaults.update(kwargs)
    return AIJob.objects.create(**defaults)


def make_input(text):
    return AIInput.objects.create(
        sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
        text=text,
        chars=len(text),
    )


def make_request(job, model, *, served=None, status='success',
                 days_ago=0, input_obj=None, **kwargs):
    defaults = {
        'job': job,
        'role': 'cheap',
        'requested_model': model,
        'served_model': served,
        'attempt': 1,
        'status': status,
        'input': input_obj,
        'prompt_layout': 'raw',
        'prompt_chars': 10,
        'prompt_sha256': 'a' * 64,
    }
    defaults.update(kwargs)
    row = AIRequest.objects.create(**defaults)
    if days_ago:
        created = timezone.now() - datetime.timedelta(days=days_ago)
        AIRequest.objects.filter(pk=row.pk).update(created_at=created)
        row.created_at = created
    return row


class UsageHelpersTests(TestCase):

    def test_parse_date(self):
        self.assertEqual(
            usage.parse_date('2024-01-15'),
            datetime.date(2024, 1, 15),
        )
        self.assertIsNone(usage.parse_date(''))
        self.assertIsNone(usage.parse_date('not-a-date'))
        self.assertIsNone(usage.parse_date(None))

    def test_default_date_range_is_30_days(self):
        date_from, date_to = usage.default_date_range()
        self.assertEqual(date_to, timezone.localdate())
        self.assertEqual(
            (date_to - date_from).days, usage.DEFAULT_USAGE_DAYS - 1
        )


class UsageAggregationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.provider = make_provider()
        cls.m1 = make_model(cls.provider, name='m1')
        cls.m2 = make_model(cls.provider, name='m2')
        cls.j1 = make_job(slug='job.one')
        cls.j2 = make_job(slug='job.two')
        make_request(
            cls.j1, cls.m1, served=cls.m1,
            input_tokens=100, output_tokens=50,
            cost_usd=Decimal('0.001'),
        )
        make_request(
            cls.j1, cls.m1, served=cls.m1,
            input_tokens=200, output_tokens=80,
            cost_usd=Decimal('0.002'),
        )
        make_request(cls.j1, cls.m1, served=cls.m1, status='blocked')
        make_request(cls.j1, cls.m1, status='error')
        make_request(
            cls.j2, cls.m2, served=cls.m2,
            input_tokens=10, output_tokens=5,
            cost_usd=Decimal('0.005'),
        )
        make_request(cls.j1, cls.m2, served=cls.m2, days_ago=1)

    def _row(self, rows, day, job_id, served_id):
        for row in rows:
            if (
                row['day'] == day
                and row['job_id'] == job_id
                and row['served_model_id'] == served_id
            ):
                return row
        self.fail(
            f'no row for day={day} job={job_id} served={served_id}'
        )

    def test_requests_by_day_aggregation(self):
        rows = list(usage.requests_by_day())
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        self.assertEqual(len(rows), 4)

        row = self._row(rows, today, self.j1.id, self.m1.id)
        self.assertEqual(row['job__slug'], 'job.one')
        self.assertEqual(row['served_model__name'], 'm1')
        self.assertEqual(row['request_count'], 3)
        self.assertEqual(row['error_count'], 0)
        self.assertEqual(row['blocked_count'], 1)
        self.assertEqual(row['input_tokens'], 300)
        self.assertEqual(row['output_tokens'], 130)
        self.assertEqual(row['cost_usd'], Decimal('0.003000'))

        # Failed requests have no served model: own bucket.
        row = self._row(rows, today, self.j1.id, None)
        self.assertEqual(row['request_count'], 1)
        self.assertEqual(row['error_count'], 1)
        self.assertIsNone(row['served_model__name'])

        row = self._row(rows, today, self.j2.id, self.m2.id)
        self.assertEqual(row['request_count'], 1)
        self.assertEqual(row['cost_usd'], Decimal('0.005000'))

        row = self._row(rows, yesterday, self.j1.id, self.m2.id)
        self.assertEqual(row['request_count'], 1)

    def test_usage_totals(self):
        totals = usage.usage_totals()
        self.assertEqual(totals['request_count'], 6)
        self.assertEqual(totals['error_count'], 1)
        self.assertEqual(totals['blocked_count'], 1)
        self.assertEqual(totals['input_tokens'], 310)
        self.assertEqual(totals['output_tokens'], 135)
        self.assertEqual(totals['cost_usd'], Decimal('0.008000'))

    def test_date_range_filter(self):
        today = timezone.localdate()
        rows = list(usage.requests_by_day(date_from=today))
        self.assertEqual(
            sum(r['request_count'] for r in rows), 5
        )
        yesterday = today - datetime.timedelta(days=1)
        rows = list(
            usage.requests_by_day(
                date_from=yesterday, date_to=yesterday
            )
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['request_count'], 1)

    def test_input_storage_totals(self):
        make_input('alpha')
        make_input('beta!')
        storage = usage.input_storage_totals()
        self.assertEqual(storage['input_count'], 2)
        self.assertEqual(storage['input_chars'], 10)


class UsageAdminViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username='admin', email='a@b.c', password='pw',
        )
        cls.provider = make_provider()
        cls.m1 = make_model(cls.provider, name='m1')
        cls.j1 = make_job(slug='job.one')

    def setUp(self):
        self.client.force_login(self.user)

    def test_usage_page_renders_rows(self):
        make_request(self.j1, self.m1, served=self.m1)
        make_request(self.j1, self.m1, served=self.m1)
        make_request(self.j1, self.m1, status='error')
        url = reverse('admin:ai_providers_airequest_usage')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'job.one')
        self.assertContains(response, 'gemini:m1')
        # Totals: 3 requests, 1 error.
        self.assertContains(response, '3')
        self.assertContains(response, '1')

    def test_usage_page_date_params(self):
        make_request(self.j1, self.m1, served=self.m1, days_ago=10)
        url = reverse('admin:ai_providers_airequest_usage')
        response = self.client.get(url, {'from': '2020-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'job.one')
        response = self.client.get(url, {'to': '2020-01-01'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'job.one')

    def test_changelist_links_usage(self):
        response = self.client.get(
            reverse('admin:ai_providers_airequest_changelist')
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, reverse('admin:ai_providers_airequest_usage')
        )


class AdminUsageColumnTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(
            username='admin2', email='b@b.c', password='pw',
        )
        cls.provider = make_provider()
        cls.m1 = make_model(cls.provider, name='m1')
        cls.j1 = make_job(slug='job.one')

    def _request(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user
        return request

    def test_job_admin_annotations(self):
        make_request(
            self.j1, self.m1, served=self.m1,
            cost_usd=Decimal('0.010'),
        )
        make_request(
            self.j1, self.m1, served=self.m1, days_ago=10,
            cost_usd=Decimal('0.020'),
        )
        make_request(self.j1, self.m1, served=self.m1, days_ago=40)
        admin = AIJobAdmin(AIJob, AdminSite())
        job = admin.get_queryset(self._request()).get(pk=self.j1.pk)
        self.assertEqual(job.requests_today, 1)
        self.assertEqual(job.cost_30d, Decimal('0.030'))

    def test_model_admin_annotations(self):
        make_request(
            self.j1, self.m1, served=self.m1,
            cost_usd=Decimal('0.010'),
        )
        make_request(self.j1, self.m1, status='error')  # requested
        make_request(self.j1, self.m1, days_ago=40)
        admin = AIModelAdmin(AIModel, AdminSite())
        model = admin.get_queryset(self._request()).get(pk=self.m1.pk)
        self.assertEqual(model.requests_today, 2)
        self.assertEqual(model.cost_30d, Decimal('0.010'))


class PruneCommandTests(TransactionTestCase):
    """Prune behavior, including FK-reference protection.

    ``TransactionTestCase`` (not ``TestCase``) because creating the
    FakeAnalysis table needs the schema editor, which SQLite cannot
    run inside ``TestCase``'s atomic wrapper. The table is created
    for every test because the globally-registered FakeAnalysis
    relation is queried by ``referenced_request_pks()`` on every
    prune run.
    """

    def setUp(self):
        self.provider = make_provider()
        self.m1 = make_model(self.provider, name='m1')
        self.j1 = make_job(slug='job.one')
        # Pick up the FakeAnalysis relation even if _meta caches were
        # populated before the test module imported it.
        AIRequest._meta._expire_cache()
        with connection.schema_editor() as editor:
            editor.create_model(FakeAnalysis)
        self.addCleanup(self._drop_fake_table)

    def _drop_fake_table(self):
        FakeAnalysis.objects.all().delete()
        with connection.schema_editor() as editor:
            editor.delete_model(FakeAnalysis)
        AIRequest._meta._expire_cache()

    def _run(self, *args):
        out = io.StringIO()
        call_command('prune_ai_requests', *args, stdout=out)
        return out.getvalue()

    def test_referenced_request_pks_introspection(self):
        referenced = make_request(self.j1, self.m1, days_ago=40)
        free = make_request(self.j1, self.m1, days_ago=40)
        FakeAnalysis.objects.create(ai_request=referenced)
        self.assertIn(referenced.pk, referenced_request_pks())
        self.assertNotIn(free.pk, referenced_request_pks())

    def test_prune_skips_referenced_requests(self):
        referenced = make_request(self.j1, self.m1, days_ago=40)
        free = make_request(self.j1, self.m1, days_ago=40)
        FakeAnalysis.objects.create(ai_request=referenced)
        output = self._run('--older-than-days', '30')
        self.assertTrue(
            AIRequest.objects.filter(pk=referenced.pk).exists()
        )
        self.assertFalse(
            AIRequest.objects.filter(pk=free.pk).exists()
        )
        self.assertIn('kept (referenced by FK)', output)

    def test_prune_deletes_old_unreferenced(self):
        old = make_request(self.j1, self.m1, days_ago=40)
        recent = make_request(self.j1, self.m1, days_ago=5)
        output = self._run('--older-than-days', '30')
        self.assertFalse(AIRequest.objects.filter(pk=old.pk).exists())
        self.assertTrue(
            AIRequest.objects.filter(pk=recent.pk).exists()
        )
        self.assertIn('1 AIRequest rows older than 30', output)

    def test_prune_deletes_orphaned_inputs_keeps_shared(self):
        shared = make_input('shared input')
        orphan = make_input('orphaned input')
        old = make_request(
            self.j1, self.m1, days_ago=40, input_obj=shared,
        )
        recent = make_request(
            self.j1, self.m1, days_ago=1, input_obj=shared,
        )
        make_request(self.j1, self.m1, days_ago=40)
        self._run('--older-than-days', '30')
        self.assertFalse(AIRequest.objects.filter(pk=old.pk).exists())
        # Shared input survives via the recent request; the never-
        # referenced orphan is removed.
        self.assertTrue(AIInput.objects.filter(pk=shared.pk).exists())
        self.assertFalse(AIInput.objects.filter(pk=orphan.pk).exists())

    def test_prune_removes_input_orphaned_by_deletion(self):
        only_old = make_input('only old')
        make_request(
            self.j1, self.m1, days_ago=40, input_obj=only_old,
        )
        self._run('--older-than-days', '30')
        self.assertFalse(
            AIInput.objects.filter(pk=only_old.pk).exists()
        )

    def test_dry_run_writes_nothing(self):
        old = make_request(self.j1, self.m1, days_ago=40)
        orphan = make_input('orphan')
        output = self._run(
            '--older-than-days', '30', '--dry-run',
        )
        self.assertIn('[dry-run]', output)
        self.assertIn('1 AIRequest rows older than 30', output)
        self.assertIn('1 AIInput rows would be deleted', output)
        self.assertTrue(AIRequest.objects.filter(pk=old.pk).exists())
        self.assertTrue(AIInput.objects.filter(pk=orphan.pk).exists())

    def test_batch_size_splits_deletes(self):
        for _ in range(3):
            make_request(self.j1, self.m1, days_ago=40)
        self._run(
            '--older-than-days', '30', '--batch-size', '1',
        )
        self.assertEqual(AIRequest.objects.count(), 0)
