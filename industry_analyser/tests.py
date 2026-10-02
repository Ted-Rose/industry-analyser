"""Root-urlconf routing tests — the <path:subpath> catch-all at the
site root must not swallow misses under prefixes owned by earlier
mounts (/api/, /admin/, /static/).
"""

from django.contrib.auth import get_user_model
from django.test import TestCase


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

    def test_arbitrary_path_still_serves_shell(self):
        """Client routes still reach the SPA shell via the
        catch-all (login bounce for anon, shell for authed)."""
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/login/', resp['Location'])
        user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )
        self.client.force_login(user)
        resp = self.client.get('/some/client/route')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')
