"""The accounts stub page is retired — /accounts/ 301s to '/'."""

from django.test import TestCase
from django.urls import reverse


class AccountsRedirectTests(TestCase):

    def test_accounts_redirects_to_root(self):
        resp = self.client.get('/accounts/')
        self.assertRedirects(
            resp,
            '/',
            status_code=301,
            fetch_redirect_response=False,
        )

    def test_accounts_name_still_reverses(self):
        self.assertEqual(reverse('accounts'), '/accounts/')
