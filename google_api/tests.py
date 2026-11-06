import json
import os
import tempfile
from datetime import timedelta, timezone as dtz
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from google.auth.exceptions import RefreshError

from .models import GoogleOAuthCredentials
from .utils import GOOGLE_TASKS_SCOPES, get_user_credentials

SECRETS = {
    'web': {
        'client_id': 'cid.apps.googleusercontent.com',
        'client_secret': 'secret',
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }
}

ACCESS_TOKEN = 'access-token-deadbee0'
REFRESH_TOKEN = 'refresh-token-deadbee0'


class CredentialsTestCase(TestCase):
    """Base: temp client-secrets file + a user with a creds row."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        fd, cls.secrets_path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w') as f:
            json.dump(SECRETS, f)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.secrets_path)
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='owner', password='x',
        )
        self._secrets = override_settings(
            GOOGLE_APP_SECRETS_PATH=self.secrets_path,
        )
        self._secrets.enable()
        self.addCleanup(self._secrets.disable)

    def _row(self, expired=False, scopes=None, refresh=REFRESH_TOKEN):
        expiry = timezone.now() + timedelta(
            hours=-1 if expired else 1
        )
        return GoogleOAuthCredentials.objects.create(
            user=self.user,
            access_token=ACCESS_TOKEN,
            refresh_token=refresh,
            token_expiry=expiry,
            scopes=scopes if scopes is not None
            else list(GOOGLE_TASKS_SCOPES),
        )


class GetUserCredentialsTests(CredentialsTestCase):
    def test_valid_row_returns_credentials(self):
        self._row()
        creds = get_user_credentials(self.user, GOOGLE_TASKS_SCOPES)
        self.assertIsNotNone(creds)
        self.assertEqual(creds.token, ACCESS_TOKEN)
        self.assertEqual(creds.refresh_token, REFRESH_TOKEN)
        # google-auth expects naive-UTC expiry
        self.assertIsNone(creds.expiry.tzinfo)

    def test_no_row_returns_none(self):
        self.assertIsNone(
            get_user_credentials(self.user, GOOGLE_TASKS_SCOPES)
        )

    def test_missing_scope_returns_none(self):
        self._row(scopes=['https://www.googleapis.com/auth/gmail.readonly'])
        self.assertIsNone(
            get_user_credentials(self.user, GOOGLE_TASKS_SCOPES)
        )

    def test_expired_token_refreshes_and_persists(self):
        self._row(expired=True)
        new_expiry = (
            timezone.now() + timedelta(hours=1)
        ).replace(tzinfo=None)

        def fake_refresh(creds, request):
            creds.token = 'at2'
            creds.expiry = new_expiry

        with patch(
            'google.oauth2.credentials.Credentials.refresh',
            fake_refresh,
        ):
            creds = get_user_credentials(self.user)
        self.assertIsNotNone(creds)
        row = GoogleOAuthCredentials.objects.get(user=self.user)
        self.assertEqual(row.access_token, 'at2')
        self.assertEqual(
            row.token_expiry, new_expiry.replace(tzinfo=dtz.utc)
        )

    def test_refresh_error_returns_none_row_unchanged(self):
        self._row(expired=True)
        with patch(
            'google.oauth2.credentials.Credentials.refresh',
            side_effect=RefreshError('revoked'),
        ):
            creds = get_user_credentials(self.user)
        self.assertIsNone(creds)
        row = GoogleOAuthCredentials.objects.get(user=self.user)
        self.assertEqual(row.access_token, ACCESS_TOKEN)


class OAuthFlowTests(CredentialsTestCase):
    def test_anonymous_login_redirects_to_django_login(self):
        response = self.client.get('/google/login/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith('/accounts/login/')
        )

    def test_anonymous_callback_redirects_to_django_login(self):
        response = self.client.get('/google/callback')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.url.startswith('/accounts/login/')
        )

    def test_unconfigured_login_answers_503(self):
        self.client.force_login(self.user)
        with override_settings(GOOGLE_APP_SECRETS_PATH=''):
            response = self.client.get('/google/login/')
        self.assertEqual(response.status_code, 503)

    def test_login_stashes_state_and_redirects(self):
        self.client.force_login(self.user)
        with patch(
            'google_auth_oauthlib.flow.InstalledAppFlow.'
            'authorization_url',
            return_value=('https://accounts.google.com/o/oauth2/auth',
                          'state-1'),
        ):
            response = self.client.get('/google/login/?next=/news/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url, 'https://accounts.google.com/o/oauth2/auth'
        )
        session = self.client.session
        self.assertEqual(session['state'], 'state-1')
        self.assertEqual(session['oauth_redirect_url'], '/news/')
        self.assertEqual(
            session['oauth_scopes'], GOOGLE_TASKS_SCOPES
        )


class AdminTests(CredentialsTestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            username='admin', password='x', email='a@b.c',
        )
        self.row = self._row()

    def test_tokens_never_rendered_on_change_page(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            f'/admin/google_api/googleoauthcredentials/'
            f'{self.row.pk}/change/'
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(ACCESS_TOKEN, content)
        self.assertNotIn(REFRESH_TOKEN, content)

    def test_token_fields_excluded_from_admin(self):
        from django.contrib import admin
        model_admin = admin.site._registry[GoogleOAuthCredentials]
        self.assertNotIn('access_token', model_admin.fields)
        self.assertNotIn('refresh_token', model_admin.fields)
