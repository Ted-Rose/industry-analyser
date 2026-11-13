"""Session-auth tests — /api/accounts/ register/login/logout/me,
the case-insensitive backend, the accounts SPA mount, and the
staff-vs-registered-vs-anonymous access matrix."""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()

API = '/api/accounts'

REGISTER_PAYLOAD = {
    'username': 'alice',
    'password': 'S3cure!pass',
    'password_confirm': 'S3cure!pass',
}


def post(client, path, payload):
    return client.post(
        path,
        data=json.dumps(payload),
        content_type='application/json',
    )


def make_user(username='alice', password='pw', **kwargs):
    return User.objects.create_user(
        username=username, password=password, **kwargs
    )


class AccountsMountTests(TestCase):
    """The /accounts/ mount serves the public accounts SPA shell —
    the retired 301 stub is gone; the 'accounts' URL name is kept
    so reverse('accounts') callers still resolve."""

    def test_accounts_name_still_reverses(self):
        self.assertEqual(reverse('accounts'), '/accounts/')

    def test_login_page_serves_spa_shell(self):
        resp = self.client.get('/accounts/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')
        self.assertContains(resp, 'spa-bootstrap')
        # The shell guarantees a csrftoken cookie — the register/
        # login ops enforce CSRF inline (auth=None).
        self.assertIn('csrftoken', resp.cookies)

    def test_register_and_index_serve_shell(self):
        for url in ('/accounts/', '/accounts/register/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, 'id="root"')

    def test_non_get_404s(self):
        resp = self.client.post('/accounts/login/')
        self.assertEqual(resp.status_code, 404)


class RegisterTests(TestCase):
    URL = f'{API}/register/'

    def test_register_success_auto_logs_in(self):
        resp = post(self.client, self.URL, REGISTER_PAYLOAD)
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['user']['username'], 'alice')
        self.assertEqual(body['user']['email'], '')
        self.assertFalse(body['user']['is_staff'])
        # The session now authenticates subsequent requests.
        me = self.client.get(f'{API}/me/')
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.json()['is_authenticated'])
        self.assertEqual(me.json()['user']['username'], 'alice')

    def test_register_with_email(self):
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'email': 'a@example.com'},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            User.objects.get(username='alice').email,
            'a@example.com',
        )

    def test_blank_email_stored_empty_and_reusable(self):
        first = post(self.client, self.URL, REGISTER_PAYLOAD)
        self.assertEqual(first.status_code, 201)
        second = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'username': 'bob', 'email': ''},
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(User.objects.get(username='bob').email, '')

    def test_username_with_whitespace_400(self):
        for username in ('al ice', ' alice', 'alice\t'):
            resp = post(
                self.client, self.URL,
                {**REGISTER_PAYLOAD, 'username': username},
            )
            self.assertEqual(resp.status_code, 400, username)
            self.assertEqual(
                resp.json()['code'], 'invalid_username'
            )
        self.assertFalse(User.objects.exists())

    def test_username_taken_case_insensitive(self):
        make_user('alice')
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'username': 'ALICE'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'username_taken')

    def test_email_taken_case_insensitive(self):
        make_user('bob', email='a@example.com')
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'email': 'A@EXAMPLE.com'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'email_taken')

    def test_weak_passwords_400(self):
        weak = (
            'short',            # minimum length
            'password',         # too common
            '123456789012',     # numeric-only
            'alice123',         # too similar to the username
        )
        for password in weak:
            resp = post(
                self.client, self.URL,
                {**REGISTER_PAYLOAD, 'password': password,
                 'password_confirm': password},
            )
            self.assertEqual(resp.status_code, 400, password)
            self.assertEqual(
                resp.json()['code'], 'weak_password'
            )
        self.assertFalse(User.objects.exists())

    def test_password_mismatch_400(self):
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'password_confirm': 'different!'},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'password_mismatch')
        self.assertFalse(User.objects.exists())

    def test_overlong_fields_4xx_not_500(self):
        """Schema caps reject over-long input before create_user —
        an over-150-char username or over-254-char email would
        otherwise DataError on Postgres and 500."""
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'username': 'a' * 151},
        )
        self.assertIn(resp.status_code, (400, 422))
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'email': 'a' * 250 + '@x.co'},
        )
        self.assertIn(resp.status_code, (400, 422))
        self.assertFalse(User.objects.exists())

    def test_email_is_stripped(self):
        resp = post(
            self.client, self.URL,
            {**REGISTER_PAYLOAD, 'email': '  a@example.com  '},
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(
            User.objects.get(username='alice').email,
            'a@example.com',
        )

    def test_csrf_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = post(csrf_client, self.URL, REGISTER_PAYLOAD)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.exists())


class LoginTests(TestCase):
    URL = f'{API}/login/'

    def setUp(self):
        self.user = make_user('Alice', password='S3cure!pass')

    def test_case_insensitive_login(self):
        resp = post(
            self.client, self.URL,
            {'username': 'alice', 'password': 'S3cure!pass'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['user']['username'], 'Alice')
        me = self.client.get(f'{API}/me/')
        self.assertTrue(me.json()['is_authenticated'])

    def test_exact_case_wins_over_case_variants(self):
        """Legacy DBs can hold case-duplicate rows — the backend
        prefers the exact-case match deterministically."""
        make_user('ALICE', password='S3cure!pass')
        resp = post(
            self.client, self.URL,
            {'username': 'ALICE', 'password': 'S3cure!pass'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['user']['username'], 'ALICE')

    def test_uniform_credential_failure(self):
        """Unknown username, wrong password and inactive accounts
        all get the identical 401 body — no user enumeration."""
        cases = (
            {'username': 'ghost', 'password': 'S3cure!pass'},
            {'username': 'alice', 'password': 'wrong-pass'},
        )
        bodies = []
        for payload in cases:
            resp = post(self.client, self.URL, payload)
            self.assertEqual(resp.status_code, 401, payload)
            body = resp.json()
            self.assertEqual(body['error'], 'unauthenticated')
            self.assertEqual(body['code'], 'invalid_credentials')
            self.assertNotIn('login_url', body)
            bodies.append(body)
        self.user.is_active = False
        self.user.save()
        resp = post(
            self.client, self.URL,
            {'username': 'alice', 'password': 'S3cure!pass'},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), bodies[1])

    def test_csrf_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        resp = post(
            csrf_client, self.URL,
            {'username': 'alice', 'password': 'S3cure!pass'},
        )
        self.assertEqual(resp.status_code, 403)


class LogoutTests(TestCase):
    URL = f'{API}/logout/'

    def test_logout_ends_session(self):
        self.client.force_login(make_user('alice'))
        resp = post(self.client, self.URL, {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'success': True})
        me = self.client.get(f'{API}/me/')
        self.assertFalse(me.json()['is_authenticated'])

    def test_anonymous_logout_401s(self):
        resp = post(self.client, self.URL, {})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()['error'], 'unauthenticated')
        self.assertIn('login_url', resp.json())


class MeTests(TestCase):
    URL = f'{API}/me/'

    def test_anonymous_200(self):
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {'user': None, 'is_authenticated': False},
        )

    def test_authenticated_200(self):
        user = make_user('alice', email='a@example.com')
        self.client.force_login(user)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(),
            {
                'user': {
                    'id': user.id,
                    'username': 'alice',
                    'email': 'a@example.com',
                    'is_staff': False,
                },
                'is_authenticated': True,
            },
        )


class AccessMatrixTests(TestCase):
    """Staff ops 403 registered users and 401 anonymous callers;
    per-user surfaces stay open to any authenticated user."""

    STAFF_GETS = (
        '/api/dashboard/',
        '/api/receipts/',
    )

    def setUp(self):
        self.registered = make_user('alice')
        self.staff = make_user('root', is_staff=True)

    def _staff_post(self, url, payload):
        for user, expected in (
            (self.registered, 403),
            (self.staff, None),
        ):
            self.client.force_login(user)
            resp = post(self.client, url, payload)
            if expected is not None:
                self.assertEqual(resp.status_code, expected, url)
                self.assertEqual(
                    resp.json()['error'], 'forbidden', url
                )
            else:
                # Success ops on these endpoints return 200 —
                # a hard assert keeps the matrix honest.
                self.assertEqual(resp.status_code, 200, url)

    def test_staff_gets_403_non_staff_and_401_anonymous(self):
        for url in self.STAFF_GETS:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 401, url)
            self.assertIn('login_url', resp.json())
            self.client.force_login(self.registered)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 403, url)
            self.assertEqual(resp.json()['error'], 'forbidden')
            self.client.logout()

    def test_staff_posts_403_non_staff(self):
        self._staff_post(
            '/api/vacancies/keywords/', {'name': 'python'},
        )
        self._staff_post(
            '/api/classified-ads/regions/config/',
            {'kind': 'apartment', 'regions': []},
        )

    def test_registered_user_reaches_per_user_surfaces(self):
        self.client.force_login(self.registered)
        resp = post(
            self.client,
            '/api/vacancies/filters/',
            {'name': 'my-filter'},
        )
        self.assertEqual(resp.status_code, 201)
        resp = self.client.get('/news/preferences/')
        self.assertEqual(resp.status_code, 200)

    def test_staff_pages_bounce_non_staff_to_admin_login(self):
        """staff_member_required sends both anonymous and
        non-staff visitors to the admin login — never to
        /accounts/login/."""
        for url in ('/dashboard/', '/receipts/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/admin/login/', resp['Location'])
            self.client.force_login(self.registered)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/admin/login/', resp['Location'])
            self.client.logout()

    def test_staff_pages_serve_staff(self):
        self.client.force_login(self.staff)
        for url in ('/dashboard/', '/receipts/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertContains(resp, 'id="root"')

    def test_public_reads_stay_public(self):
        resp = self.client.get('/api/vacancies/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get('/api/vacancies/filters/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_bootstrap_carries_auth_flags(self):
        """Every SPA shell injects is_authenticated/is_staff."""
        resp = self.client.get('/accounts/')
        self.assertContains(
            resp, '"is_authenticated": false', status_code=200
        )
        self.client.force_login(self.staff)
        resp = self.client.get('/dashboard/')
        self.assertContains(resp, '"is_authenticated": true')
        self.assertContains(resp, '"is_staff": true')
