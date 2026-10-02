"""Dashboard SPA cutover tests — the login-required root mount and
the /api/dashboard/ auth contract."""

import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scrape_jobs.models import (
    ScrapeJob,
    ScrapeJobItem,
    ScrapeJobRun,
    ScrapeJobRunItem,
)


def make_job(slug='test.job', **kwargs):
    return ScrapeJob.objects.create(slug=slug, **kwargs)


def make_run(job, status=ScrapeJobRun.SUCCESS, **kwargs):
    kwargs.setdefault('cycle_key', '2026-01-05')
    kwargs.setdefault('execution_id', 'local-test-1')
    kwargs.setdefault('executed_by', 'local')
    return ScrapeJobRun.objects.create(
        job=job, status=status, **kwargs
    )


class DashboardShellTests(TestCase):
    """The dashboard SPA owns the site root; the shell is
    login-required (react_app — the only non-public SPA)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )

    def test_root_anonymous_redirects_to_login(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp['Location'], '/admin/login/?next=/'
        )

    def test_root_authed_serves_shell(self):
        self.client.force_login(self.user)
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')
        self.assertContains(resp, 'spa-bootstrap')

    def test_deep_link_serves_shell(self):
        """The root catch-all serves the shell for client routes —
        anonymous callers are bounced to login first."""
        self.client.force_login(self.user)
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')

    def test_deep_link_anonymous_redirects_to_login(self):
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp['Location'])

    def test_non_get_root_404s(self):
        """react_app answers GET/HEAD only — the method check fires
        before login_required, so even anonymous POSTs get a 404,
        not a login redirect."""
        for method in ('post', 'put', 'delete'):
            resp = getattr(self.client, method)('/')
            self.assertEqual(resp.status_code, 404)
        self.client.force_login(self.user)
        resp = self.client.post('/')
        self.assertEqual(resp.status_code, 404)

    def test_home_still_reverses_to_root(self):
        self.assertEqual(reverse('home'), '/')


class DashboardApiTests(TestCase):
    """GET /api/dashboard/ — session-authed (the page it replaced
    was @login_required)."""

    API = '/api/dashboard'

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )

    def test_anonymous_401_json_login_url_root(self):
        """Session auth fails as JSON, never a redirect; SPA_BASES
        maps /api/dashboard/* back to '/', so login_url's `next` is
        the SPA page, not the JSON endpoint."""
        resp = self.client.get(f'{self.API}/')
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body['error'], 'unauthenticated')
        self.assertEqual(
            body['login_url'], '/admin/login/?next=%2F'
        )

    def test_dashboard_payload(self):
        self.client.force_login(self.user)
        job = make_job()
        item = ScrapeJobItem.objects.create(job=job, key='k1')
        run = make_run(job)
        ScrapeJobRun.objects.filter(pk=run.pk).update(
            completed_at=timezone.now()
        )
        ScrapeJobRunItem.objects.create(
            run=run, item=item, status=ScrapeJobRunItem.DONE
        )
        resp = self.client.get(f'{self.API}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['jobs']), 1)
        job_row = body['jobs'][0]
        self.assertEqual(job_row['job']['slug'], 'test.job')
        self.assertTrue(job_row['job']['is_enabled'])
        self.assertEqual(job_row['item_active'], 1)
        self.assertEqual(job_row['cycle_done'], 1)
        self.assertEqual(job_row['progress_pct'], 100)
        self.assertFalse(job_row['running'])
        self.assertEqual(
            job_row['last_run']['status'], 'SUCCESS'
        )
        self.assertIsNotNone(
            job_row['last_run']['duration_seconds']
        )
        self.assertEqual(len(body['rows']), 1)
        day_row = body['rows'][0]
        self.assertEqual(day_row['job_slug'], 'test.job')
        self.assertEqual(day_row['run_count'], 1)
        self.assertEqual(day_row['success_count'], 1)
        self.assertEqual(body['totals']['run_count'], 1)
        # The effective window is echoed back for the filter form.
        self.assertIn('date_from', body)
        self.assertIn('date_to', body)

    def test_date_window_params(self):
        """?date_from=/&date_to= bound the daily table; the jobs
        table is unaffected."""
        self.client.force_login(self.user)
        job = make_job()
        run = make_run(job)
        ScrapeJobRun.objects.filter(pk=run.pk).update(
            started_at=datetime.datetime(
                2020, 1, 1, tzinfo=datetime.timezone.utc
            )
        )
        resp = self.client.get(
            f'{self.API}/',
            {'date_from': '2026-01-01', 'date_to': '2026-01-31'},
        )
        body = resp.json()
        self.assertEqual(body['rows'], [])
        self.assertEqual(body['totals']['run_count'], 0)
        self.assertEqual(len(body['jobs']), 1)
        self.assertEqual(body['date_from'], '2026-01-01')
        self.assertEqual(body['date_to'], '2026-01-31')

    def test_invalid_date_param_422s(self):
        """The retired view silently fell back to defaults on bad
        input; the API validates like the sibling SPAs do."""
        self.client.force_login(self.user)
        resp = self.client.get(
            f'{self.API}/', {'date_from': 'bogus'}
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(
            resp.json()['error'], 'validation_error'
        )
