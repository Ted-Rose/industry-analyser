"""Root-urlconf routing tests — the terminal <path:subpath>
catch-all (which renders the public landing page) must not swallow
misses under prefixes owned by earlier mounts (/api/, /admin/,
/static/).
"""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from industry_analyser import api as api_module
from industry_analyser.sentry import (
    capture_internal_exception,
    capture_provider_exception,
    sentry_before_send,
)


class CatchAllDrainTests(TestCase):
    """terminal_404 patterns sit just before the root catch-all so
    resolver misses under api//admin//static/ stay real 404s."""

    def test_api_miss_404s_not_shell(self):
        for url in ('/api/nonexistent/', '/api/nonexistent'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 404, url)
            self.assertNotIn(b'id="root"', resp.content)

    def test_unslashed_api_url_redirects_not_shell(self):
        """/api/dashboard raised a Resolver404 inside the ninja
        mount; the drain keeps the 404 so CommonMiddleware's
        APPEND_SLASH can still redirect."""
        resp = self.client.get('/api/dashboard')
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(
            resp['Location'].endswith('/api/dashboard/')
        )

    def test_admin_miss_never_serves_shell(self):
        """Admin's own catch_all_view resolves /admin/* misses inside
        its mount — anonymous visitors get the login bounce, staff a
        real 404; neither sees the SPA shell."""
        resp = self.client.get('/admin/definitely-not-a-page/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp['Location'])
        staff = get_user_model().objects.create_user(
            username='root', password='pw', is_staff=True
        )
        self.client.force_login(staff)
        resp = self.client.get('/admin/definitely-not-a-page/')
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b'id="root"', resp.content)

    def test_static_miss_404s_not_shell(self):
        resp = self.client.get('/static/no-such-file.js')
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(b'id="root"', resp.content)

    def test_legit_api_route_still_resolves(self):
        resp = self.client.get('/api/vacancies/')
        self.assertEqual(resp.status_code, 200)

    def test_admin_index_still_resolves(self):
        resp = self.client.get('/admin/')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp['Location'])

    def test_arbitrary_path_serves_landing(self):
        """Unknown paths fall through to the terminal catch-all,
        which renders the public landing page (the app directory)
        instead of a bare 404 — for anon and authed alike."""
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Industry Analyser')
        user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )
        self.client.force_login(user)
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Industry Analyser')


class LandingPageTests(TestCase):
    """The public landing page at / auto-discovers the top-level
    app mounts off the root urlconf (views._landing_entries) — a
    new mount needs no edit to appear."""

    def test_root_is_public_and_lists_apps(self):
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        for url in (
            '/vacancies/', '/companies/', '/classified-ads/',
            '/tv/', '/receipts/', '/news/',
        ):
            self.assertContains(resp, f'href="{url}"')

    def test_dashboard_cta_is_flagged_login_required(self):
        resp = self.client.get('/')
        self.assertContains(resp, 'href="/dashboard/"')
        self.assertContains(resp, 'Web scraping results')
        self.assertContains(resp, 'login required')

    def test_infra_mounts_and_self_are_excluded(self):
        from industry_analyser.views import _landing_entries
        urls = {e['url'] for e in _landing_entries()}
        for excluded in (
            '/api/', '/admin/', '/accounts/', '/add_keyword/',
        ):
            self.assertNotIn(excluded, urls)
        self.assertNotIn('/', urls)  # the page never lists itself

    def test_receipts_mount_is_login_required(self):
        from industry_analyser.views import _landing_entries
        entries = {e['url']: e for e in _landing_entries()}
        self.assertTrue(entries['/receipts/']['login_required'])
        self.assertFalse(entries['/vacancies/']['login_required'])

    def test_post_to_landing_404s(self):
        self.assertEqual(self.client.post('/').status_code, 404)
        self.assertEqual(
            self.client.post('/typo/path').status_code, 404
        )


class SentryHelpersTests(SimpleTestCase):
    """sentry.py capture helpers are complete no-ops when the SDK
    was never initialized (no SENTRY_DSN — always true in tests)."""

    def test_capture_helpers_noop_without_dsn(self):
        # No exception, no configured transport — the calls must
        # simply return None.
        self.assertIsNone(
            capture_internal_exception(RuntimeError('boom'))
        )
        self.assertIsNone(
            capture_provider_exception(
                RuntimeError('boom'), 'provider_error'
            )
        )
        self.assertIsNone(
            capture_provider_exception(
                RuntimeError('boom'), 'rate_limited'
            )
        )

    def test_provider_error_code_allowlist(self):
        with self.assertRaises(ValueError):
            capture_provider_exception(
                RuntimeError('boom'), 'internal_error'
            )
        with self.assertRaises(ValueError):
            capture_provider_exception(
                RuntimeError('boom'), 'nonsense'
            )

    def test_before_send_strips_admin_request_body(self):
        event = {
            'request': {
                'url': 'https://x.example/admin/login/',
                'method': 'POST',
                'data': {'password': 's3cret'},
            }
        }
        result = sentry_before_send(event, {})
        self.assertNotIn('data', result['request'])
        # URL and method survive so the event stays debuggable.
        self.assertEqual(result['request']['method'], 'POST')

    def test_before_send_strips_accounts_request_body(self):
        """Register/login bodies carry passwords — /api/accounts/
        is a sensitive prefix like /admin/."""
        for url in (
            'https://x.example/api/accounts/register/',
            'https://x.example/api/accounts/login/',
        ):
            event = {
                'request': {
                    'url': url,
                    'method': 'POST',
                    'data': {'password': 's3cret'},
                }
            }
            result = sentry_before_send(event, {})
            self.assertNotIn('data', result['request'], url)

    def test_before_send_keeps_other_request_bodies(self):
        event = {
            'request': {
                'url': 'https://x.example/api/vacancies/',
                'data': {'keywords': 'python'},
            }
        }
        result = sentry_before_send(event, {})
        self.assertEqual(
            result['request']['data'], {'keywords': 'python'}
        )

    def test_before_send_tolerates_missing_or_nondict_request(self):
        event = {'request': 'not-a-dict'}
        self.assertIs(sentry_before_send(event, {}), event)
        event = {}
        self.assertIs(sentry_before_send(event, {}), event)

    def test_before_send_strips_body_when_url_undeterminable(self):
        """Fail closed: a missing or malformed url can't be checked
        against the sensitive prefixes, so the body goes anyway."""
        for request in (
            {'data': {'password': 's3cret'}},
            {'url': 'not-a-url', 'data': {'password': 's3cret'}},
            {'url': '', 'data': {'password': 's3cret'}},
        ):
            event = {'request': dict(request)}
            result = sentry_before_send(event, {})
            self.assertNotIn('data', result['request'], request)


class UnhandledApiErrorTests(SimpleTestCase):
    """_on_unhandled_error replaced ninja's default Exception
    handler — it must keep the uniform 500 body, report to Sentry,
    and log the traceback itself so DSN-less environments (local
    dev, pre-secret deploys) don't lose it."""

    def test_raising_endpoint_returns_uniform_500_and_captures(self):
        exc = RuntimeError('boom')
        request = RequestFactory().get('/api/vacancies/')
        with self.assertLogs('industry_analyser', level='ERROR'), \
                patch(
                    'industry_analyser.api.capture_internal_exception'
                ) as capture:
            resp = api_module._on_unhandled_error(request, exc)
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(
            json.loads(resp.content),
            {
                'error': 'server_error',
                'detail': 'Internal Server Error',
            },
        )
        capture.assert_called_once_with(exc)
