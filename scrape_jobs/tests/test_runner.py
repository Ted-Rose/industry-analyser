"""ScrapeJobRunner unit tests — no HTTP, no real scrapers."""

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from core_scraper.base import BaseScraper
from scrape_jobs.models import (
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)
from scrape_jobs.runner import (
    ITEM_FAILURE_MARKER,
    ScrapeJobRunner,
    detect_executed_by,
    detect_execution_id,
    ensure_job,
)


def _entries(*specs):
    """(key, priority[, obj]) specs → (key, label, priority, obj)."""
    result = []
    for spec in specs:
        key, priority = spec[0], spec[1]
        obj = spec[2] if len(spec) > 2 else key
        result.append((key, key.upper(), priority, obj))
    return result


class EnsureJobTests(TestCase):

    def test_creates_job_and_syncs_description(self):
        job = ensure_job('test.job', 'first')
        self.assertEqual(job.description, 'first')
        again = ensure_job('test.job', 'second')
        self.assertEqual(again.pk, job.pk)
        self.assertEqual(again.description, 'second')
        self.assertEqual(ScrapeJob.objects.count(), 1)


class EnvDetectionTests(TestCase):

    def test_local_by_default(self):
        with mock.patch.dict('os.environ', {}, clear=True):
            self.assertEqual(detect_executed_by(), 'local')
            self.assertTrue(
                detect_execution_id().startswith('local-')
            )

    def test_cloud_run_detection(self):
        env = {
            'K_SERVICE': 'x',
            'CLOUD_RUN_EXECUTION': 'exec-1',
            'CLOUD_RUN_TASK_INDEX': '2',
        }
        with mock.patch.dict('os.environ', env, clear=True):
            self.assertEqual(detect_executed_by(), 'gcp_cloud_run')
            self.assertEqual(detect_execution_id(), 'exec-1-2')


class RunnerInitTests(TestCase):

    def test_creates_running_run(self):
        runner = ScrapeJobRunner('test.job', description='d')
        self.assertEqual(runner.run.status, ScrapeJobRun.RUNNING)
        self.assertEqual(runner.run.cycle_key, runner.cycle_key)
        self.assertEqual(runner.run.executed_by, 'local')
        self.assertEqual(runner.completed_keys, set())

    def test_stale_run_swept_to_abandoned(self):
        job = ScrapeJob.objects.create(slug='test.job')
        stale_run = ScrapeJobRun.objects.create(
            job=job, cycle_key='2000-01-01', execution_id='e',
            executed_by='local',
        )
        ScrapeJobRun.objects.filter(pk=stale_run.pk).update(
            updated_at=timezone.now() - timedelta(minutes=31)
        )
        ScrapeJobRunner('test.job')
        stale_run.refresh_from_db()
        self.assertEqual(stale_run.status, ScrapeJobRun.ABANDONED)
        self.assertIsNotNone(stale_run.completed_at)

    def test_fresh_running_run_is_not_swept(self):
        job = ScrapeJob.objects.create(slug='test.job')
        live = ScrapeJobRun.objects.create(
            job=job, cycle_key='c', execution_id='e',
            executed_by='local',
        )
        ScrapeJobRunner('test.job')
        live.refresh_from_db()
        self.assertEqual(live.status, ScrapeJobRun.RUNNING)


def _make_runner(slug='test.job', **kwargs):
    return ScrapeJobRunner(slug, **kwargs)


def _done_item(runner, key):
    item = ScrapeJobItem.objects.get(job=runner.job, key=key)
    runner.item_done(item)
    return item


class CompletedKeysTests(TestCase):

    def setUp(self):
        self.runner = _make_runner()
        self.runner.sync_items(_entries(('a', 0), ('b', 0), ('c', 0)))

    def test_done_items_skipped_next_run_same_cycle(self):
        _done_item(self.runner, 'a')
        self.runner.finish(ScrapeJobRun.PARTIAL)

        r2 = ScrapeJobRunner('test.job')
        self.assertEqual(r2.completed_keys, {'a'})
        pending = r2.pending_items(r2.sync_items(
            _entries(('a', 0), ('b', 0), ('c', 0))
        ))
        self.assertEqual([i.key for i in pending], ['b', 'c'])

    def test_completed_union_covers_all_cycle_runs(self):
        """A chain of failures: keys done by ANY run in the cycle
        are skipped — not just the latest run's tail."""
        _done_item(self.runner, 'a')
        self.runner.finish(ScrapeJobRun.ABANDONED)

        r2 = ScrapeJobRunner('test.job')
        _done_item(
            r2, 'b'
        )
        r2.finish(ScrapeJobRun.ABANDONED)

        r3 = ScrapeJobRunner('test.job')
        self.assertEqual(r3.completed_keys, {'a', 'b'})

    def test_success_run_in_cycle_means_fresh_pass(self):
        _done_item(self.runner, 'a')
        self.runner.finish()  # SUCCESS

        r2 = ScrapeJobRunner('test.job')
        self.assertEqual(r2.completed_keys, set())

    def test_partial_run_still_resumes(self):
        """PARTIAL (some items failed) is not SUCCESS — resume."""
        _done_item(self.runner, 'a')
        self.runner.finish(ScrapeJobRun.PARTIAL)

        r2 = ScrapeJobRunner('test.job')
        self.assertEqual(r2.completed_keys, {'a'})

    def test_fresh_flag_ignores_completed(self):
        _done_item(self.runner, 'a')
        self.runner.finish(ScrapeJobRun.PARTIAL)

        r2 = ScrapeJobRunner('test.job', fresh=True)
        self.assertEqual(r2.completed_keys, set())

    def test_disabled_job_never_skips(self):
        _done_item(self.runner, 'a')
        self.runner.finish(ScrapeJobRun.PARTIAL)

        self.runner.job.is_enabled = False
        self.runner.job.save()
        r2 = ScrapeJobRunner('test.job')
        self.assertEqual(r2.completed_keys, set())

    def test_failed_items_are_not_skipped(self):
        item = ScrapeJobItem.objects.get(job=self.runner.job, key='a')
        self.runner.item_failed(item, ValueError('boom'))
        self.runner.finish()

        r2 = ScrapeJobRunner('test.job')
        self.assertEqual(r2.completed_keys, set())


class PendingItemsTests(TestCase):

    def setUp(self):
        self.runner = _make_runner()

    def test_priority_ordering_high_first(self):
        items = self.runner.sync_items(
            _entries(('low', 0), ('high', 10), ('mid', 5))
        )
        pending = self.runner.pending_items(items)
        self.assertEqual(
            [i.key for i in pending], ['high', 'mid', 'low']
        )

    def test_inactive_items_skipped(self):
        items = self.runner.sync_items(_entries(('a', 0), ('b', 0)))
        items[0].is_active = False
        items[0].save()
        pending = self.runner.pending_items(items)
        self.assertEqual([i.key for i in pending], ['b'])

    def test_resume_from_drops_earlier_items(self):
        items = self.runner.sync_items(
            _entries(('a', 0), ('b', 0), ('c', 0))
        )
        runner = ScrapeJobRunner('test.job', resume_from='b')
        pending = runner.pending_items(items)
        self.assertEqual([i.key for i in pending], ['b', 'c'])

    def test_resume_from_unknown_key_raises(self):
        items = self.runner.sync_items(_entries(('a', 0)))
        runner = ScrapeJobRunner('test.job', resume_from='zzz')
        with self.assertRaises(ValueError):
            runner.pending_items(items)


class SyncItemsTests(TestCase):

    def test_get_or_create_and_label_refresh(self):
        runner = _make_runner()
        items = runner.sync_items(_entries(('a', 0, 'obj-a')))
        self.assertEqual(items[0].obj, 'obj-a')

        runner2 = ScrapeJobRunner('test.job')
        items2 = runner2.sync_items([('a', 'NEW-LABEL', 99, 'x')])
        self.assertEqual(items2[0].pk, items[0].pk)
        # label refreshed; priority (admin-owned) untouched
        self.assertEqual(items2[0].label, 'NEW-LABEL')
        self.assertEqual(items2[0].priority, 0)

    def test_vanished_source_deactivates_item(self):
        runner = _make_runner()
        runner.sync_items(_entries(('a', 0), ('b', 0)))
        runner2 = ScrapeJobRunner('test.job')
        runner2.sync_items(_entries(('a', 0)))
        item_b = ScrapeJobItem.objects.get(job=runner.job, key='b')
        self.assertFalse(item_b.is_active)


class ItemRecordingTests(TestCase):

    def setUp(self):
        self.runner = _make_runner()
        self.items = self.runner.sync_items(_entries(('a', 0)))

    def test_item_done_marks_run_item_and_last_completed(self):
        item = self.items[0]
        self.runner.item_done(item)
        ri = ScrapeJobRunItem.objects.get(
            run=self.runner.run, item=item
        )
        self.assertEqual(ri.status, ScrapeJobRunItem.DONE)
        self.runner.run.refresh_from_db()
        self.assertEqual(self.runner.run.last_completed_item, item)

    def test_item_failed_records_and_logs_marker(self):
        item = self.items[0]
        with self.assertLogs('scrape_jobs', level='ERROR') as logs:
            self.runner.item_failed(item, RuntimeError('kaput'))
        self.assertTrue(
            any(ITEM_FAILURE_MARKER in line for line in logs.output)
        )
        ri = ScrapeJobRunItem.objects.get(
            run=self.runner.run, item=item
        )
        self.assertEqual(ri.status, ScrapeJobRunItem.FAILED)
        self.assertIn('kaput', ri.error_message)
        self.assertEqual(self.runner.failed_item_count, 1)

    def test_finish_defaults_to_partial_after_item_failure(self):
        self.runner.item_failed(self.items[0], ValueError('x'))
        self.runner.finish()
        self.runner.run.refresh_from_db()
        self.assertEqual(self.runner.run.status, ScrapeJobRun.PARTIAL)
        self.assertIsNotNone(self.runner.run.completed_at)

    def test_finish_defaults_to_success(self):
        self.runner.item_done(self.items[0])
        self.runner.finish()
        self.runner.run.refresh_from_db()
        self.assertEqual(self.runner.run.status, ScrapeJobRun.SUCCESS)

    def test_finish_failed_carries_error(self):
        self.runner.finish(ScrapeJobRun.FAILED, 'traceback...')
        self.runner.run.refresh_from_db()
        self.assertEqual(self.runner.run.status, ScrapeJobRun.FAILED)
        self.assertEqual(self.runner.run.error_message, 'traceback...')

    def test_touch_updates_heartbeat(self):
        old = timezone.now() - timedelta(minutes=5)
        ScrapeJobRun.objects.filter(pk=self.runner.run.pk).update(
            updated_at=old
        )
        self.runner.run.refresh_from_db()
        self.runner.touch()
        self.runner.run.refresh_from_db()
        self.assertGreater(self.runner.run.updated_at, old)


class DryRunTests(TestCase):

    def test_dry_run_writes_nothing(self):
        runner = ScrapeJobRunner('test.job', dry_run=True)
        items = runner.sync_items(_entries(('a', 0), ('b', 0)))
        pending = runner.pending_items(items)
        self.assertEqual([i.key for i in pending], ['a', 'b'])
        runner.item_done(items[0])
        runner.item_failed(items[1], ValueError('x'))
        runner.touch()
        runner.finish()
        self.assertEqual(ScrapeJob.objects.count(), 0)
        self.assertEqual(ScrapeJobRun.objects.count(), 0)
        self.assertEqual(ScrapeJobRunItem.objects.count(), 0)


class _StubScraper(BaseScraper):
    """Minimal scraper exercising run()'s exception-throw contract:
    scrape_portal() failures are thrown back into get_search_urls(),
    where the per-item try/except isolates them."""

    def __init__(self, runner, fail_on=()):
        super().__init__()
        self.runner = runner
        self.fail_on = fail_on
        self.scraped = []

    def get_search_urls(self):
        items = self.runner.sync_items(
            _entries(('a', 0), ('b', 0), ('c', 0))
        )
        for item in self.runner.pending_items(items):
            try:
                yield f'http://x/{item.key}'
                self.runner.touch()
            except Exception as e:
                self.runner.item_failed(item, e)
                continue
            self.runner.item_done(item)

    def scrape_portal(self, url):
        self.scraped.append(url)
        if url.rsplit('/', 1)[-1] in self.fail_on:
            raise RuntimeError(f'boom {url}')
        return []

    def create_or_update_resources(self, resources):
        pass


class RunIsolationTests(TestCase):
    """BaseScraper.run() + ScrapeJobRunner: a failing item does not
    abort the run — it is recorded FAILED and iteration continues."""

    def test_failing_item_isolated_run_continues(self):
        runner = _make_runner()
        scraper = _StubScraper(runner, fail_on={'b'})
        scraper.run()

        self.assertEqual(
            scraper.scraped,
            ['http://x/a', 'http://x/b', 'http://x/c'],
        )
        statuses = dict(
            ScrapeJobRunItem.objects.filter(run=runner.run)
            .values_list('item__key', 'status')
        )
        self.assertEqual(
            statuses, {'a': 'DONE', 'b': 'FAILED', 'c': 'DONE'}
        )

        runner.finish()
        runner.run.refresh_from_db()
        self.assertEqual(runner.run.status, ScrapeJobRun.PARTIAL)

    def test_fatal_error_outside_items_propagates(self):
        runner = _make_runner()

        class FatalScraper(_StubScraper):
            def get_search_urls(self):
                yield 'http://x/plain'  # no try/except around yield

        scraper = FatalScraper(runner, fail_on={'plain'})
        with self.assertRaises(RuntimeError):
            scraper.run()

    def test_second_run_resumes_completed_items(self):
        r1 = _make_runner()
        _StubScraper(r1, fail_on={'b'}).run()
        r1.finish()

        r2 = ScrapeJobRunner('test.job')
        s2 = _StubScraper(r2)
        s2.run()
        # 'a' and 'c' were DONE in this cycle; only the FAILED item
        # 'b' is re-processed.
        self.assertEqual(s2.scraped, ['http://x/b'])
