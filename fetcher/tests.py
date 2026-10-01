"""Tests for the cv.lv public-portal (Next.js) scraping path.

Covers ``__NEXT_DATA__`` extraction, offset pagination, detail-page
enrichment, vacancy-file OCR and Vacancy/VacancyFile persistence.

No real HTTP or AI calls: ``scraper.make_request`` is replaced by a
Mock returning ``SimpleNamespace(data=..., headers=...)`` fakes, and
``scraper._ai_client`` is a stub whose ``generate()`` returns canned
text.
"""

import hashlib
import json
import types
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from ai_providers import errors as ai_errors
from fetcher.models import Keyword, Vacancy, VacancyFile
from fetcher.scraper import VacancyScrapper

CONFIG = {
    'type': 'nextjs',
    'base_url': 'https://www.cv.lv',
    'search_href': '/lv/search',
    'search_params': 'categories%5B0%5D=INFORMATION_TECHNOLOGY',
    'page_size': 2,
    'vacancy_base_url': 'https://www.cv.lv',
    'vacancy_base_href': '/lv/vacancy/',
    'files_href': '/api/v1/files-service/',
}


def next_data_html(payload):
    return (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + '</script>'
    ).encode('utf-8')


def response(data=b'', content_type='text/html'):
    return types.SimpleNamespace(
        data=data, headers={'Content-Type': content_type}
    )


def search_response(vacancies, total):
    payload = {
        'props': {
            'pageProps': {
                'searchResults': {
                    'vacancies': vacancies,
                    'total': total,
                },
            },
        },
    }
    return response(next_data_html(payload))


def detail_response(vacancy_id, file_id=None, sections=None):
    payload = {
        'props': {
            'pageProps': {
                'vacancy': {
                    str(vacancy_id): vacancy_detail(file_id, sections),
                },
            },
        },
    }
    return response(next_data_html(payload))


def vacancy_detail(file_id=None, sections=None):
    return {
        'details': {
            'fileDetails': {'fileId': file_id} if file_id else None,
            'standardDetails': sections or [],
        },
    }


def vacancy_result(vacancy_id=1, **overrides):
    result = {
        'id': vacancy_id,
        'positionTitle': 'Python developer',
        'employerName': 'Acme SIA',
        'publishDate': '2025-06-01T10:00:00+03:00',
        'keywords': [],
        'categories': [],
        'salaryFrom': 1000,
        'salaryTo': 2000,
        'expirationDate': '2025-07-01T10:00:00+03:00',
        'renewedDate': '2025-06-01T10:00:00+03:00',
    }
    result.update(overrides)
    return result


def make_vacancy(vacancy_portal_id, **kwargs):
    defaults = {
        'vacancy_portal_id': vacancy_portal_id,
        'title': 'Stored vacancy',
        'url': 'https://www.cv.lv/lv/vacancy/'
               + str(vacancy_portal_id),
        'first_seen': timezone.now(),
        'state': 'CREATED',
    }
    defaults.update(kwargs)
    return Vacancy.objects.create(**defaults)


class NextJsScraperTestCase(TestCase):
    """A VacancyScrapper built on the nextjs cv.lv config."""

    def setUp(self):
        super().setUp()
        with mock.patch.object(
            VacancyScrapper, 'load_config', return_value=CONFIG
        ):
            self.scraper = VacancyScrapper(portal_id=99)

    def stub_ai_client(self, text='OCR TEXT'):
        """Drop-in AI client whose generate() returns canned text."""
        client = mock.Mock()
        client.generate.return_value = types.SimpleNamespace(
            text=text, served_model=None, ai_request=None,
        )
        self.scraper._ai_client = client
        return client


class NextJsParseResultsTests(NextJsScraperTestCase):

    def test_extracts_vacancies_and_total(self):
        vacancies = [vacancy_result(1), vacancy_result(2)]
        results = self.scraper.parse_results(
            search_response(vacancies, total=5)
        )
        self.assertEqual(results, vacancies)
        self.assertEqual(self.scraper._search_total, 5)

    def test_missing_next_data_returns_empty(self):
        results = self.scraper.parse_results(
            response(b'<html><p>no data</p></html>')
        )
        self.assertEqual(results, [])

    def test_invalid_next_data_json_returns_empty(self):
        html = (
            '<script id="__NEXT_DATA__">not json</script>'
        ).encode('utf-8')
        self.assertEqual(self.scraper.parse_results(response(html)), [])

    def test_none_response_returns_empty(self):
        self.assertEqual(self.scraper.parse_results(None), [])


class NextJsPaginationTests(NextJsScraperTestCase):

    def feed_pages(self, pages):
        """Drive get_search_urls() the way scrape_portal does:
        each yielded URL is fetched and parsed, and
        last_search_had_results is set from the parse outcome."""
        urls = []
        generator = self.scraper.get_search_urls()
        for page in pages:
            urls.append(next(generator))
            results = self.scraper.parse_results(page)
            self.scraper.last_search_had_results = bool(results)
        return urls, generator

    def test_paginates_until_offset_reaches_total(self):
        pages = [
            search_response(
                [vacancy_result(1), vacancy_result(2)], total=3
            ),
            search_response([vacancy_result(3)], total=3),
        ]
        urls, generator = self.feed_pages(pages)
        with self.assertRaises(StopIteration):
            next(generator)
        params = 'categories%5B0%5D=INFORMATION_TECHNOLOGY'
        self.assertEqual(
            urls,
            [
                'https://www.cv.lv/lv/search?limit=2&offset=0&'
                + params,
                'https://www.cv.lv/lv/search?limit=2&offset=2&'
                + params,
            ],
        )

    def test_stops_on_empty_page_even_below_total(self):
        pages = [
            search_response([vacancy_result(1)], total=10),
            search_response([], total=10),
        ]
        urls, generator = self.feed_pages(pages)
        with self.assertRaises(StopIteration):
            next(generator)
        self.assertEqual(len(urls), 2)
        self.assertIn('offset=2', urls[1])


class NeedsDetailFetchTests(NextJsScraperTestCase):

    def test_new_vacancy_needs_fetch(self):
        self.assertTrue(
            self.scraper._needs_detail_fetch(vacancy_result(7))
        )

    def test_missing_id_needs_no_fetch(self):
        result = vacancy_result(7)
        del result['id']
        self.assertFalse(self.scraper._needs_detail_fetch(result))

    def test_fetched_and_not_renewed_skips_fetch(self):
        make_vacancy(7, detail_fetched_at=timezone.now())
        result = vacancy_result(
            7, renewedDate='2025-06-01T10:00:00+03:00'
        )
        self.assertFalse(self.scraper._needs_detail_fetch(result))

    def test_renewed_after_fetch_needs_fetch(self):
        make_vacancy(
            7,
            detail_fetched_at=timezone.now() - timedelta(days=5),
        )
        result = vacancy_result(
            7, renewedDate=timezone.now().isoformat()
        )
        self.assertTrue(self.scraper._needs_detail_fetch(result))

    def test_unparseable_renewed_date_needs_fetch(self):
        make_vacancy(7, detail_fetched_at=timezone.now())
        result = vacancy_result(7, renewedDate='not-a-date')
        self.assertTrue(self.scraper._needs_detail_fetch(result))


class EnrichResultTests(NextJsScraperTestCase):

    def test_skips_fetch_when_detail_is_fresh(self):
        make_vacancy(7, detail_fetched_at=timezone.now())
        self.scraper.make_request = mock.Mock()
        result = vacancy_result(
            7, renewedDate='2025-06-01T10:00:00+03:00'
        )
        self.assertIs(self.scraper.enrich_result(result), result)
        self.scraper.make_request.assert_not_called()

    def test_fetches_detail_page_and_merges_it(self):
        self.scraper.make_request = mock.Mock(
            return_value=detail_response(
                7,
                file_id='file-7',
                sections=[
                    {'title': 'About', 'content': '<b>Nice</b> job'},
                ],
            )
        )
        result = vacancy_result(7)
        enriched = self.scraper.enrich_result(result)
        self.scraper.make_request.assert_called_once_with(
            'https://www.cv.lv/lv/vacancy/7'
        )
        self.assertNotIn('_detail', result)  # original untouched
        detail = enriched['_detail']
        self.assertEqual(
            detail['details']['fileDetails']['fileId'], 'file-7'
        )
        self.assertEqual(
            detail['details']['standardDetails'][0]['title'], 'About'
        )

    def test_fetch_failure_returns_result_unchanged(self):
        self.scraper.make_request = mock.Mock(return_value=None)
        result = vacancy_result(7)
        with self.assertLogs('fetcher', level='WARNING'):
            self.assertIs(self.scraper.enrich_result(result), result)

    def test_missing_detail_json_returns_result_unchanged(self):
        self.scraper.make_request = mock.Mock(
            return_value=response(b'<html><p>oops</p></html>')
        )
        result = vacancy_result(7)
        with self.assertLogs('fetcher', level='WARNING'):
            self.assertIs(self.scraper.enrich_result(result), result)


class BuildVacancyTests(NextJsScraperTestCase):

    def test_detail_enriches_vacancy_and_stages_file(self):
        client = self.stub_ai_client('OCR RESULT')
        self.scraper.make_request = mock.Mock(
            return_value=response(b'IMG-BYTES', 'image/png')
        )
        result = vacancy_result(9)
        result['_detail'] = vacancy_detail(
            file_id='file-9',
            sections=[
                {'title': 'Duties', 'content': '<b>Write</b> code'},
                {'title': 'Empty', 'content': None},
            ],
        )
        vacancy = self.scraper.initiate_resource(result)
        self.assertIsNotNone(vacancy.detail_fetched_at)
        extra = result['_extra_content']
        # get_text(' ') splits at tag boundaries, leaving the
        # section text flattened but possibly double-spaced.
        self.assertIn('Write', extra)
        self.assertIn('code', extra)
        self.assertIn('OCR RESULT', extra)
        pending = vacancy._pending_file
        self.assertIsInstance(pending, VacancyFile)
        self.assertIsNone(pending.pk)
        self.assertEqual(pending.file_id, 'file-9')
        self.assertEqual(pending.content_type, 'image/png')
        self.assertEqual(
            pending.sha256,
            hashlib.sha256(b'IMG-BYTES').hexdigest(),
        )
        self.assertEqual(pending.extracted_text, 'OCR RESULT')
        client.generate.assert_called_once()
        spec = client.generate.call_args.args[0]
        self.assertEqual(spec.images[0].data, b'IMG-BYTES')
        self.assertEqual(spec.images[0].mime_type, 'image/png')

    def test_no_detail_leaves_vacancy_plain(self):
        self.scraper.make_request = mock.Mock()
        result = vacancy_result(9)
        vacancy = self.scraper.initiate_resource(result)
        self.assertIsNone(vacancy.detail_fetched_at)
        self.assertNotIn('_extra_content', result)
        self.assertFalse(hasattr(vacancy, '_pending_file'))
        self.assertEqual(
            vacancy.url, 'https://www.cv.lv/lv/vacancy/9'
        )
        self.assertEqual(vacancy.vacancy_portal_id, 9)
        self.assertEqual(vacancy.title, 'Python developer')
        self.scraper.make_request.assert_not_called()


class OcrVacancyFileTests(NextJsScraperTestCase):

    def test_cached_file_reuses_stored_text(self):
        vacancy = make_vacancy(5)
        VacancyFile.objects.create(
            vacancy=vacancy,
            file_id='cached-file',
            content_type='image/png',
            sha256='0' * 64,
            extracted_text='STORED TEXT',
        )
        self.scraper.make_request = mock.Mock()
        client = self.stub_ai_client()
        text, pending = self.scraper._ocr_vacancy_file('cached-file')
        self.assertEqual(text, 'STORED TEXT')
        self.assertIsNone(pending)
        self.scraper.make_request.assert_not_called()
        client.generate.assert_not_called()

    def test_file_fetch_failure_returns_empty(self):
        self.scraper.make_request = mock.Mock(return_value=None)
        text, pending = self.scraper._ocr_vacancy_file('gone')
        self.assertEqual((text, pending), ('', None))

    def test_non_ocr_content_type_skips_ai(self):
        self.scraper.make_request = mock.Mock(
            return_value=response(b'<html></html>', 'text/html')
        )
        client = self.stub_ai_client()
        text, pending = self.scraper._ocr_vacancy_file('html-file')
        self.assertEqual((text, pending), ('', None))
        client.generate.assert_not_called()

    def test_ai_error_returns_empty_and_no_file(self):
        client = self.stub_ai_client()
        client.generate.side_effect = ai_errors.AIError('nope')
        self.scraper.make_request = mock.Mock(
            return_value=response(b'data', 'image/png')
        )
        text, pending = self.scraper._ocr_vacancy_file('bad-file')
        self.assertEqual((text, pending), ('', None))

    def test_request_cap_marks_ocr_unavailable(self):
        client = self.stub_ai_client()
        client.generate.side_effect = (
            ai_errors.AIRequestCapReached('cap')
        )
        self.scraper.make_request = mock.Mock(
            return_value=response(b'data', 'image/png')
        )
        text, pending = self.scraper._ocr_vacancy_file('cap-file')
        self.assertEqual((text, pending), ('', None))
        self.assertTrue(self.scraper._ocr_unavailable)
        # Later files short-circuit before any HTTP or AI call.
        self.scraper.make_request.reset_mock()
        text, pending = self.scraper._ocr_vacancy_file('later-file')
        self.assertEqual((text, pending), ('', None))
        self.scraper.make_request.assert_not_called()


class CreateOrUpdateResourcesTests(NextJsScraperTestCase):

    def _scrape_enriched(self, result):
        """initiate_resource + create_or_update_resources."""
        vacancy = self.scraper.initiate_resource(result)
        self.scraper.create_or_update_resources([vacancy])
        return vacancy

    def test_persists_vacancy_file_and_keywords(self):
        Keyword.objects.create(name='python')
        Keyword.objects.create(name='ocrword')
        self.scraper.keywords_list = list(Keyword.objects.all())
        self.stub_ai_client('has OCRWORD inside')
        self.scraper.make_request = mock.Mock(
            return_value=response(b'IMG', 'image/png')
        )
        result = vacancy_result(
            42, positionTitle='Software developer'
        )
        result['_detail'] = vacancy_detail(
            file_id='file-42',
            sections=[
                {'title': 'About',
                 'content': '<p>Seeking a python guru</p>'},
            ],
        )
        self._scrape_enriched(result)

        stored = Vacancy.objects.get(vacancy_portal_id=42)
        self.assertEqual(stored.title, 'Software developer')
        self.assertIsNotNone(stored.detail_fetched_at)
        vacancy_file = VacancyFile.objects.get(file_id='file-42')
        self.assertEqual(vacancy_file.vacancy, stored)
        self.assertEqual(
            vacancy_file.extracted_text, 'has OCRWORD inside'
        )
        self.assertEqual(vacancy_file.content_type, 'image/png')
        self.assertEqual(
            vacancy_file.sha256, hashlib.sha256(b'IMG').hexdigest()
        )
        # 'python' from detail text, 'ocrword' only via OCR output.
        names = set(stored.keywords.values_list('name', flat=True))
        self.assertEqual(names, {'python', 'ocrword'})

    def test_existing_vacancy_updated_in_place(self):
        existing = make_vacancy(42)
        Keyword.objects.create(name='python')
        self.scraper.keywords_list = list(Keyword.objects.all())
        self.stub_ai_client('OCR TEXT')
        self.scraper.make_request = mock.Mock(
            return_value=response(b'IMG', 'image/png')
        )
        result = vacancy_result(42)
        result['_detail'] = vacancy_detail(
            file_id='file-42',
            sections=[{'title': 'A', 'content': 'python work'}],
        )
        self._scrape_enriched(result)
        self.assertEqual(Vacancy.objects.count(), 1)
        existing.refresh_from_db()
        self.assertIsNotNone(existing.detail_fetched_at)
        # Existing title is kept (only blanks get filled in).
        self.assertEqual(existing.title, 'Stored vacancy')
        vacancy_file = VacancyFile.objects.get(file_id='file-42')
        self.assertEqual(vacancy_file.vacancy, existing)

    def test_vacancy_without_detail_still_persists(self):
        result = vacancy_result(43)
        self._scrape_enriched(result)
        stored = Vacancy.objects.get(vacancy_portal_id=43)
        self.assertIsNone(stored.detail_fetched_at)
        self.assertFalse(VacancyFile.objects.exists())
