from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse


class DailySightingsReportViewTest(TestCase):
    def test_daily_sightings_report_loads(self):
        url = reverse('classified_ads:daily_sightings_report')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Daily Sightings Report')

    def test_daily_sightings_with_date_range(self):
        date_from = (date.today() - timedelta(days=7)).isoformat()
        date_to = date.today().isoformat()
        url = reverse('classified_ads:daily_sightings_report')
        response = self.client.get(
            url,
            {'date_from': date_from, 'date_to': date_to}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, date_from)
        self.assertContains(response, date_to)
