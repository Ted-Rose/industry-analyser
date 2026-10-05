"""Tests for the cv.lv public-portal (Next.js) scraping path.

Covers ``__NEXT_DATA__`` extraction, offset pagination, detail-page
enrichment, vacancy-file OCR and Vacancy/VacancyFile persistence.

No real HTTP or AI calls: ``scraper.make_request`` is replaced by a
Mock returning ``SimpleNamespace(data=..., headers=...)`` fakes, and
``scraper._ai_client`` is a stub whose ``generate()`` returns canned
text.
"""

import hashlib
import io
import json
import types
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ai_providers import errors as ai_errors
from django.core.management import call_command
from django.core.management.base import CommandError

from fetcher import company_linking
from fetcher.models import (
    Company,
    CompanyAlias,
    CompanyIdentity,
    Industry,
    Keyword,
    Vacancy,
    VacancyContainsKeyword,
    VacancyFile,
    VacancyIndustries,
)
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

API_CONFIG = {
    'type': 'api',
    'base_url': 'https://www.cv.lv',
    'search_href': '/api/v1/vacancy-search-service/search',
    'search_params': 'categories%5B0%5D=INFORMATION_TECHNOLOGY',
    'page_size': 2,
    'vacancy_base_url': 'https://www.cv.lv',
    'vacancy_base_href': '/lv/vacancy/',
    'files_href': '/api/v1/files-service/',
    'industry_mapping': {'10': 'it'},
}

LEGACY_API_CONFIG = {
    'type': 'api',
    'base_url': 'https://www.cv.lv',
    'search_href': '/api/v1/vacancy-search-service/search',
    'vacancy_base_url': 'https://www.cv.lv',
    'vacancy_base_href': '/lv/vacancy/',
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


def api_response(vacancies, total):
    return response(
        json.dumps(
            {'vacancies': vacancies, 'total': total}
        ).encode('utf-8'),
        'application/json',
    )


def drive_pages(scraper, pages):
    """Drive get_search_urls() the way scrape_portal does:
    each yielded URL is fetched and parsed, and
    last_search_had_results is set from the parse outcome."""
    urls = []
    generator = scraper.get_search_urls()
    for page in pages:
        urls.append(next(generator))
        results = scraper.parse_results(page)
        scraper.last_search_had_results = bool(results)
    return urls, generator


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

    def test_paginates_until_offset_reaches_total(self):
        pages = [
            search_response(
                [vacancy_result(1), vacancy_result(2)], total=3
            ),
            search_response([vacancy_result(3)], total=3),
        ]
        urls, generator = drive_pages(self.scraper, pages)
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
        urls, generator = drive_pages(self.scraper, pages)
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


def make_scraper(config, portal_id=1):
    with mock.patch.object(
        VacancyScrapper, 'load_config', return_value=config
    ):
        return VacancyScrapper(portal_id=portal_id)


class ApiSweepTests(TestCase):
    """API portals with ``search_params`` run the same
    offset-paginated sweep as the nextjs portal."""

    def setUp(self):
        super().setUp()
        self.scraper = make_scraper(API_CONFIG)

    def test_paginates_category_sweep_until_total(self):
        pages = [
            api_response(
                [vacancy_result(1), vacancy_result(2)], total=3
            ),
            api_response([vacancy_result(3)], total=3),
        ]
        urls, generator = drive_pages(self.scraper, pages)
        with self.assertRaises(StopIteration):
            next(generator)
        base = (
            'https://www.cv.lv/api/v1/vacancy-search-service/search'
        )
        params = 'categories%5B0%5D=INFORMATION_TECHNOLOGY'
        self.assertEqual(
            urls,
            [
                f'{base}?limit=2&offset=0&{params}',
                f'{base}?limit=2&offset=2&{params}',
            ],
        )

    def test_stops_on_empty_page(self):
        pages = [
            api_response([vacancy_result(1)], total=10),
            api_response([], total=10),
        ]
        urls, generator = drive_pages(self.scraper, pages)
        with self.assertRaises(StopIteration):
            next(generator)
        self.assertEqual(len(urls), 2)

    def test_parse_results_records_total(self):
        self.scraper.parse_results(
            api_response([vacancy_result(1)], total=42)
        )
        self.assertEqual(self.scraper._search_total, 42)

    def test_non_json_response_yields_nothing(self):
        results = self.scraper.parse_results(
            response(b'<html><p>oops</p></html>', 'text/html')
        )
        self.assertEqual(results, [])

    def test_api_portal_does_not_enrich(self):
        self.assertFalse(self.scraper.enrich_search_results)


class ApiKeywordFallbackTests(TestCase):
    """API portals without ``search_params`` keep the per-keyword
    search loop."""

    def test_yields_one_url_per_searchable_keyword(self):
        Keyword.objects.create(name='python')
        Keyword.objects.create(name='django')
        Keyword.objects.create(name='filtered', only_filter=True)
        scraper = make_scraper(LEGACY_API_CONFIG)
        urls = list(scraper.get_search_urls())
        base = (
            'https://www.cv.lv/api/v1/vacancy-search-service/search'
            '?limit=1000&keywords[]='
        )
        self.assertEqual(urls, [base + 'python', base + 'django'])


class DedupTests(TestCase):

    def test_drops_ids_seen_earlier_in_the_run(self):
        scraper = make_scraper(API_CONFIG)
        results = [
            vacancy_result(1),
            vacancy_result(2),
            vacancy_result(1),
        ]
        fresh = scraper.remove_redundant_results(results)
        self.assertEqual([r['id'] for r in fresh], [1, 2])
        fresh = scraper.remove_redundant_results(
            [vacancy_result(2), vacancy_result(3)]
        )
        self.assertEqual([r['id'] for r in fresh], [3])


class BuildVacancyMetadataTests(TestCase):

    def setUp(self):
        super().setUp()
        self.scraper = make_scraper(API_CONFIG, portal_id=1)

    def test_stamps_job_portal_id(self):
        vacancy = self.scraper.initiate_resource(vacancy_result(5))
        self.assertEqual(vacancy.job_portal_id, 1)

    def test_industry_mapping_maps_categories(self):
        Industry.objects.create(name='it')
        Industry.objects.create(name='5')
        result = vacancy_result(5, categories=[10, 5])
        vacancy = self.scraper.initiate_resource(result)
        names = {i.name for i in vacancy._pending_industries}
        self.assertEqual(names, {'it', '5'})

    def test_portal_keywords_matched_by_name(self):
        Keyword.objects.create(name='python')
        self.scraper.keywords_list = list(Keyword.objects.all())
        result = vacancy_result(5, keywords=['python', 'unknown'])
        vacancy = self.scraper.initiate_resource(result)
        names = {k.name for k in vacancy._pending_keywords}
        self.assertIn('python', names)
        self.assertNotIn('unknown', names)


class BatchedPersistenceTests(TestCase):

    def setUp(self):
        super().setUp()
        self.scraper = make_scraper(API_CONFIG, portal_id=1)

    def test_unchanged_existing_vacancy_gets_sighting_bump(self):
        existing = make_vacancy(
            42,
            title='Python developer',
            company_name='Acme SIA',
            last_seen=timezone.now() - timedelta(days=3),
        )
        vacancy = self.scraper.initiate_resource(
            vacancy_result(42)
        )
        self.scraper.create_or_update_resources([vacancy])
        existing.refresh_from_db()
        self.assertGreater(
            existing.last_seen,
            timezone.now() - timedelta(days=1),
        )
        self.assertEqual(Vacancy.objects.count(), 1)

    def test_existing_vacancy_gets_m2m_rows(self):
        Keyword.objects.create(name='python')
        self.scraper.keywords_list = list(Keyword.objects.all())
        existing = make_vacancy(
            42, title='Python developer',
            company_name='Acme SIA',
        )
        vacancy = self.scraper.initiate_resource(
            vacancy_result(42)
        )
        self.scraper.create_or_update_resources([vacancy])
        self.assertEqual(
            set(existing.keywords.values_list('name', flat=True)),
            {'python'},
        )

    def test_new_vacancies_get_m2m_and_portal_stamp(self):
        Industry.objects.create(name='it')
        Keyword.objects.create(name='python')
        self.scraper.keywords_list = list(Keyword.objects.all())
        vacancy = self.scraper.initiate_resource(
            vacancy_result(77, categories=[10])
        )
        self.scraper.create_or_update_resources([vacancy])
        stored = Vacancy.objects.get(vacancy_portal_id=77)
        self.assertEqual(stored.job_portal_id, 1)
        self.assertEqual(
            set(stored.industries.values_list('name', flat=True)),
            {'it'},
        )
        self.assertEqual(
            set(stored.keywords.values_list('name', flat=True)),
            {'python'},
        )


def employer_page_detail(
    employer_id=7,
    employer_name='Acme',
    reg_code=None,
):
    """Detail-page vacancy dict carrying the employer slices the
    company linking code reads (plan §2.1)."""
    return {
        'employerId': employer_id,
        'employerName': employer_name,
        'employer': {
            'employerId': employer_id,
            'regCode': reg_code,
            'about': '<div>About us</div>',
            'webpageUrl': 'https://acme.example',
            'videoUrl': 'https://acme.example/video',
            'logoFileId': 'logo-1',
            'coverFileId': 'cover-1',
            'gallery': ['g1', 'g2'],
        },
        'contacts': {
            'firstName': 'Talent ',
            'lastName': 'Team',
            'email': 'talent@acme.example',
            'phone': '+371 123',
        },
        'settings': {'applyingUrl': 'https://ats.example/apply'},
        'highlights': {'address': 'Marijas iela 2a'},
        'details': {'standardDetails': [], 'fileDetails': None},
    }


def employer_detail_response(vacancy_id, **detail_kwargs):
    payload = {
        'props': {
            'pageProps': {
                'vacancy': {
                    str(vacancy_id): employer_page_detail(
                        **detail_kwargs
                    ),
                },
            },
        },
    }
    return response(next_data_html(payload))


class CompanyLinkingTests(TestCase):
    """employerId -> Company/CompanyIdentity linking at scrape
    time (plan PR-2)."""

    def setUp(self):
        super().setUp()
        self.scraper = make_scraper(API_CONFIG, portal_id=1)

    def _scrape(self, results):
        vacancies = [
            self.scraper.initiate_resource(r) for r in results
        ]
        self.scraper.create_or_update_resources(vacancies)
        return vacancies

    def test_new_vacancy_links_company_and_identity(self):
        self._scrape([
            vacancy_result(1, employerId=7, employerName='Acme')
        ])
        company = Company.objects.get()
        self.assertEqual(company.name, 'Acme')
        identity = CompanyIdentity.objects.get()
        self.assertEqual(identity.source, 'cv.lv')
        self.assertEqual(identity.employer_id, 7)
        self.assertEqual(identity.company, company)
        stored = Vacancy.objects.get(vacancy_portal_id=1)
        self.assertEqual(stored.company_id, company.pk)
        self.assertTrue(
            company.aliases.filter(kind='name', value='Acme')
            .exists()
        )

    def test_identity_reused_across_runs(self):
        self._scrape([vacancy_result(1, employerId=7)])
        self._scrape([vacancy_result(2, employerId=7)])
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(CompanyIdentity.objects.count(), 1)

    def test_rename_updates_name_and_records_alias(self):
        self._scrape([
            vacancy_result(1, employerId=7, employerName='Acme')
        ])
        self._scrape([
            vacancy_result(2, employerId=7, employerName='Acme Corp')
        ])
        company = Company.objects.get()
        self.assertEqual(company.name, 'Acme Corp')
        names = set(
            company.aliases.filter(kind='name')
            .values_list('value', flat=True)
        )
        self.assertEqual(names, {'Acme', 'Acme Corp'})
        # Renames are routine — no review flag.
        self.assertFalse(company.needs_review)

    def test_two_employer_ids_same_name_make_two_companies(self):
        self._scrape([
            vacancy_result(1, employerId=7, employerName='Acme'),
            vacancy_result(2, employerId=8, employerName='Acme'),
        ])
        self.assertEqual(Company.objects.count(), 2)
        self.assertEqual(CompanyIdentity.objects.count(), 2)
        employer_ids = set(
            CompanyIdentity.objects.values_list(
                'employer_id', flat=True
            )
        )
        self.assertEqual(employer_ids, {7, 8})

    def test_100_vacancies_one_employer_make_one_company(self):
        results = [
            vacancy_result(1000 + i, employerId=7)
            for i in range(100)
        ]
        self._scrape(results)
        self.assertEqual(Company.objects.count(), 1)
        self.assertEqual(CompanyIdentity.objects.count(), 1)
        self.assertEqual(
            Vacancy.objects.filter(company__isnull=False).count(),
            100,
        )

    def test_sighting_only_row_gets_company(self):
        existing = make_vacancy(
            42,
            title='Python developer',
            company_name='Acme SIA',
        )
        self._scrape([vacancy_result(42, employerId=7)])
        existing.refresh_from_db()
        self.assertEqual(
            existing.company_id,
            Company.objects.get().pk,
        )

    def test_changed_existing_row_carries_company(self):
        # A real change (fresh detail) puts the row on the
        # bulk_update path — the FK still lands.
        existing = make_vacancy(42, title=None)
        self._scrape([vacancy_result(42, employerId=7)])
        existing.refresh_from_db()
        self.assertEqual(
            existing.company_id,
            Company.objects.get().pk,
        )

    def test_merged_company_resolves_to_survivor(self):
        self._scrape([
            vacancy_result(1, employerId=7, employerName='Acme'),
            vacancy_result(2, employerId=8, employerName='Acme 2'),
        ])
        target, loser = Company.objects.order_by('name')
        company_linking.merge_companies(target, [loser])
        loser_identity = CompanyIdentity.objects.get(
            employer_id=8
        )
        self._scrape([vacancy_result(3, employerId=8)])
        stored = Vacancy.objects.get(vacancy_portal_id=3)
        self.assertEqual(stored.company_id, target.pk)
        # The stale link on vacancy 2 is repointed on its next
        # sighting too.
        self._scrape([vacancy_result(2, employerId=8)])
        self.assertEqual(
            Vacancy.objects.get(vacancy_portal_id=2).company_id,
            target.pk,
        )
        self.assertEqual(loser_identity.employer_id, 8)

    def test_missing_employer_id_leaves_company_null(self):
        self._scrape([vacancy_result(1)])
        self.assertIsNone(
            Vacancy.objects.get(vacancy_portal_id=1).company_id
        )
        self.assertFalse(Company.objects.exists())

    def test_dry_run_writes_no_companies(self):
        scraper = make_scraper(API_CONFIG, portal_id=1)
        scraper.dry_run = True
        vacancies = [
            scraper.initiate_resource(
                vacancy_result(1, employerId=7)
            )
        ]
        scraper.create_or_update_resources(vacancies)
        self.assertFalse(Company.objects.exists())
        self.assertFalse(CompanyIdentity.objects.exists())
        self.assertFalse(CompanyAlias.objects.exists())
        self.assertFalse(Vacancy.objects.exists())


class EmployerDetailEnrichmentTests(TestCase):
    """Detail-page employer fields -> Company upsert (plan PR-3)."""

    def setUp(self):
        super().setUp()
        self.scraper = make_scraper(CONFIG, portal_id=2)

    def _scrape_detail(self, vacancy_id, **detail_kwargs):
        result = vacancy_result(
            vacancy_id,
            employerId=detail_kwargs.get('employer_id', 7),
            employerName=detail_kwargs.get('employer_name', 'Acme'),
        )
        result['_detail'] = employer_page_detail(**detail_kwargs)
        vacancy = self.scraper.initiate_resource(result)
        self.scraper.create_or_update_resources([vacancy])

    def test_reg_code_normalized_and_fields_upserted(self):
        self._scrape_detail(1, reg_code=' 0749 5895 ')
        company = Company.objects.get()
        self.assertEqual(company.reg_code, '07495895')
        self.assertEqual(company.about, 'About us')
        self.assertEqual(
            company.webpage_url, 'https://acme.example'
        )
        self.assertEqual(company.logo_file_id, 'logo-1')
        self.assertEqual(company.cover_file_id, 'cover-1')
        self.assertEqual(company.gallery, ['g1', 'g2'])
        self.assertEqual(company.contact_name, 'Talent Team')
        self.assertEqual(
            company.contact_email, 'talent@acme.example'
        )
        self.assertEqual(company.contact_phone, '+371 123')
        self.assertEqual(
            company.applying_url, 'https://ats.example/apply'
        )
        self.assertEqual(company.address, 'Marijas iela 2a')
        self.assertEqual(company.raw_employer['employerId'], 7)
        self.assertIsNotNone(company.detail_fetched_at)
        self.assertFalse(company.needs_review)
        self.assertTrue(
            company.aliases.filter(
                kind='reg_code', value='07495895'
            ).exists()
        )

    def test_reg_code_change_flags_review(self):
        self._scrape_detail(1, reg_code='111')
        self._scrape_detail(2, reg_code='222')
        company = Company.objects.get()
        self.assertEqual(company.reg_code, '222')
        self.assertTrue(company.needs_review)
        codes = set(
            company.aliases.filter(kind='reg_code')
            .values_list('value', flat=True)
        )
        self.assertEqual(codes, {'111', '222'})

    def test_reg_code_collision_flags_new_company(self):
        self._scrape_detail(1, reg_code='999', employer_id=7)
        self._scrape_detail(2, reg_code='999', employer_id=8)
        self.assertEqual(Company.objects.count(), 2)
        flagged = Company.objects.get(needs_review=True)
        # Constraint can't fire — the observed code lives in the
        # alias history instead.
        self.assertIsNone(flagged.reg_code)
        self.assertTrue(
            flagged.aliases.filter(
                kind='reg_code', value='999'
            ).exists()
        )
        keeper = Company.objects.get(needs_review=False)
        self.assertEqual(keeper.reg_code, '999')

    def test_missing_reg_code_leaves_null(self):
        self._scrape_detail(1, reg_code=None)
        company = Company.objects.get()
        self.assertIsNone(company.reg_code)
        self.assertFalse(company.needs_review)


class CompanyLinkingHelperTests(TestCase):
    """Pure helpers in fetcher.company_linking."""

    def test_normalize_reg_code(self):
        self.assertEqual(
            company_linking.normalize_reg_code(' ab 12 cd '),
            'AB12CD',
        )
        self.assertIsNone(company_linking.normalize_reg_code(''))
        self.assertIsNone(company_linking.normalize_reg_code(None))
        self.assertIsNone(company_linking.normalize_reg_code('   '))

    def test_extract_vacancy_detail(self):
        data = {
            'props': {
                'pageProps': {'vacancy': {'7': {'id': 7}}},
            },
        }
        self.assertEqual(
            company_linking.extract_vacancy_detail(data, 7),
            {'id': 7},
        )
        self.assertIsNone(
            company_linking.extract_vacancy_detail(data, 8)
        )
        self.assertIsNone(
            company_linking.extract_vacancy_detail(None, 7)
        )
        self.assertIsNone(
            company_linking.extract_vacancy_detail({}, 7)
        )

    def test_employer_detail_slice(self):
        detail = employer_page_detail(reg_code='1')
        s = company_linking.employer_detail_slice(detail)
        self.assertEqual(s['employer_id'], 7)
        self.assertEqual(s['employer_name'], 'Acme')
        self.assertEqual(s['employer']['regCode'], '1')
        self.assertEqual(
            s['applying_url'], 'https://ats.example/apply'
        )
        self.assertEqual(s['address'], 'Marijas iela 2a')
        self.assertIsNone(company_linking.employer_detail_slice(None))


class LinkVacanciesToCompaniesTests(TestCase):
    """The backfill command (plan PR-4)."""

    def _run(self, *args, **kwargs):
        with mock.patch.object(
            VacancyScrapper, 'load_config', return_value=CONFIG
        ), mock.patch(
            'fetcher.management.commands.'
            'link_vacancies_to_companies.load_portals_config',
            return_value={'2': dict(CONFIG, order=1)},
        ), mock.patch.object(
            VacancyScrapper, 'make_request',
            return_value=kwargs.pop('response', None),
        ):
            call_command('link_vacancies_to_companies', *args)

    def test_links_vacancy_via_detail_page(self):
        vacancy = make_vacancy(42)
        self._run(
            '--ids', '42',
            response=employer_detail_response(
                42, reg_code=' 11 22 '
            ),
        )
        vacancy.refresh_from_db()
        self.assertIsNotNone(vacancy.company_id)
        self.assertIsNotNone(vacancy.detail_fetched_at)
        self.assertEqual(vacancy.company.reg_code, '1122')
        identity = CompanyIdentity.objects.get()
        self.assertEqual(identity.employer_id, 7)

    def test_dead_detail_page_leaves_company_null(self):
        vacancy = make_vacancy(42)
        self._run('--ids', '42', response=response(b'<html></html>'))
        vacancy.refresh_from_db()
        self.assertIsNone(vacancy.company_id)

    def test_fetch_failure_leaves_company_null(self):
        vacancy = make_vacancy(42)
        self._run('--ids', '42', response=None)
        vacancy.refresh_from_db()
        self.assertIsNone(vacancy.company_id)

    def test_dry_run_reports_only(self):
        make_vacancy(42)
        out = io.StringIO()
        with mock.patch.object(
            VacancyScrapper, 'load_config', return_value=CONFIG
        ), mock.patch(
            'fetcher.management.commands.'
            'link_vacancies_to_companies.load_portals_config',
            return_value={'2': CONFIG},
        ):
            call_command(
                'link_vacancies_to_companies',
                '--dry-run', stdout=out,
            )
        self.assertIn('dry-run', out.getvalue())
        self.assertFalse(Company.objects.exists())


class MergeCompaniesTests(TestCase):

    def test_merge_repoints_everything(self):
        target = Company.objects.create(
            name='Target', first_seen=timezone.now(),
            last_seen=timezone.now(),
        )
        loser = Company.objects.create(
            name='Loser', needs_review=True,
            first_seen=timezone.now(), last_seen=timezone.now(),
        )
        CompanyIdentity.objects.create(
            company=loser, source='cv.lv', employer_id=8,
            first_seen=timezone.now(), last_seen=timezone.now(),
        )
        loser_vacancy = make_vacancy(1, company=loser)
        CompanyAlias.objects.create(
            company=loser, kind='name', value='Loser',
            first_seen=timezone.now(), last_seen=timezone.now(),
        )
        company_linking.merge_companies(target, [loser])

        loser.refresh_from_db()
        self.assertEqual(loser.merged_into, target)
        self.assertFalse(loser.needs_review)
        loser_vacancy.refresh_from_db()
        self.assertEqual(loser_vacancy.company_id, target.pk)
        self.assertEqual(
            CompanyIdentity.objects.get(employer_id=8).company,
            target,
        )
        self.assertTrue(
            target.aliases.filter(kind='name', value='Loser')
            .exists()
        )

    def test_canonical_follows_chain(self):
        target = Company.objects.create(
            name='T', first_seen=timezone.now(),
            last_seen=timezone.now(),
        )
        loser = Company.objects.create(
            name='L', merged_into=target,
            first_seen=timezone.now(), last_seen=timezone.now(),
        )
        self.assertEqual(loser.canonical(), target)


def make_company(name='Acme', **kwargs):
    defaults = {
        'first_seen': timezone.now(),
        'last_seen': timezone.now(),
    }
    defaults.update(kwargs)
    return Company.objects.create(name=name, **defaults)


class VacanciesApiTests(TestCase):
    """HTTP-layer coverage for the vacancies SPA API (mounted at
    /api/vacancies/) and the URL cutover — the retired template
    views' behavior is covered here at the JSON boundary."""

    API = '/api/vacancies'

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='alice', password='pw'
        )

    # --- URL cutover / shell ---

    def test_vacancies_url_serves_shell(self):
        resp = self.client.get('/vacancies/')
        self.assertEqual(resp.status_code, 200)
        # The vite asset tag is gated on the built manifest — the
        # test env may not have frontend_dist/, so assert only the
        # mount point and the diagnostic bootstrap are present.
        self.assertContains(resp, 'id="root"')
        self.assertContains(resp, 'spa-bootstrap')

    def test_vacancies_deep_link_serves_shell(self):
        resp = self.client.get('/vacancies/keywords')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="root"')

    def test_companies_urls_serve_shell(self):
        company = make_company()
        for url in ('/companies/', f'/companies/{company.pk}/'):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, 'id="root"')

    def test_non_get_to_spa_urls_404s(self):
        for method in ('post', 'put', 'delete'):
            resp = getattr(self.client, method)('/vacancies/')
            self.assertEqual(resp.status_code, 404)
        resp = self.client.post('/add_keyword/')
        self.assertEqual(resp.status_code, 404)

    def test_add_keyword_redirects_into_spa(self):
        resp = self.client.get('/add_keyword/')
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp.url, '/vacancies/keywords')

    def test_named_routes_still_reverse(self):
        self.assertEqual(reverse('find_vacancies'), '/vacancies/')
        self.assertEqual(reverse('companies'), '/companies/')
        company = make_company()
        self.assertEqual(
            reverse('company_detail', kwargs={'pk': company.pk}),
            f'/companies/{company.pk}/',
        )
        self.assertEqual(reverse('add_keyword'), '/add_keyword/')

    # --- GET /api/vacancies/ ---

    def test_vacancy_list_is_public(self):
        make_vacancy(1)
        resp = self.client.get(f'{self.API}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(len(body['vacancies']), 1)
        self.assertIn('keywords', body)
        self.assertIn('industries', body)
        self.assertEqual(body['page'], 1)

    def test_vacancy_list_returns_filter_option_lists(self):
        Keyword.objects.create(name='python')
        Industry.objects.create(name='it')
        resp = self.client.get(f'{self.API}/')
        body = resp.json()
        self.assertEqual(body['keywords'], ['python'])
        self.assertEqual(body['industries'], ['it'])

    def test_include_keywords_filter(self):
        kw = Keyword.objects.create(name='python')
        match = make_vacancy(1)
        VacancyContainsKeyword.objects.create(
            vacancy=match, keyword=kw
        )
        make_vacancy(2)
        resp = self.client.get(
            f'{self.API}/', {'include_keywords': ['python']}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(
            body['vacancies'][0]['id'], str(match.pk)
        )
        self.assertEqual(body['vacancies'][0]['keywords'], ['python'])

    def test_exclude_keywords_filter(self):
        kw = Keyword.objects.create(name='java')
        excluded = make_vacancy(1)
        VacancyContainsKeyword.objects.create(
            vacancy=excluded, keyword=kw
        )
        kept = make_vacancy(2)
        resp = self.client.get(
            f'{self.API}/', {'exclude_keywords': ['java']}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['vacancies'][0]['id'], str(kept.pk))

    def test_include_industries_filter(self):
        industry = Industry.objects.create(name='it')
        match = make_vacancy(1)
        VacancyIndustries.objects.create(
            vacancy=match, industry=industry
        )
        make_vacancy(2)
        resp = self.client.get(
            f'{self.API}/', {'include_industries': ['it']}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['vacancies'][0]['id'], str(match.pk))
        self.assertEqual(body['vacancies'][0]['industries'], ['it'])

    def test_show_active_only_excludes_past_deadlines(self):
        make_vacancy(
            1,
            application_deadline=(
                timezone.now() - timedelta(days=1)
            ),
        )
        live = make_vacancy(
            2,
            application_deadline=(
                timezone.now() + timedelta(days=5)
            ),
        )
        resp = self.client.get(
            f'{self.API}/', {'show_active_only': '1'}
        )
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['vacancies'][0]['id'], str(live.pk))

    def test_pagination(self):
        for i in range(3):
            make_vacancy(10 + i)
        with mock.patch('fetcher.api.VACANCIES_PER_PAGE', 2):
            first = self.client.get(f'{self.API}/', {'page': 1})
            second = self.client.get(f'{self.API}/', {'page': 2})
        body = first.json()
        self.assertEqual(body['num_pages'], 2)
        self.assertEqual(body['total_count'], 3)
        self.assertEqual(len(body['vacancies']), 2)
        self.assertTrue(body['has_next'])
        self.assertFalse(body['has_previous'])
        self.assertEqual((body['start_index'], body['end_index']), (1, 2))
        body2 = second.json()
        self.assertEqual(len(body2['vacancies']), 1)
        self.assertTrue(body2['has_previous'])
        self.assertFalse(body2['has_next'])

    def test_out_of_range_page_returns_last_page(self):
        make_vacancy(1)
        resp = self.client.get(f'{self.API}/', {'page': 99})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['page'], 1)

    def test_non_integer_page_422s(self):
        resp = self.client.get(f'{self.API}/', {'page': 'abc'})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['error'], 'validation_error')

    # --- GET /api/vacancies/companies/ ---

    def test_company_list_is_public(self):
        company = make_company('Acme')
        resp = self.client.get(f'{self.API}/companies/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        row = body['companies'][0]
        self.assertEqual(row['id'], str(company.pk))
        self.assertEqual(row['name'], 'Acme')
        self.assertEqual(row['vacancy_count'], 0)

    def test_company_list_query_filter(self):
        make_company('Acme', reg_code='1234')
        make_company('Other')
        resp = self.client.get(f'{self.API}/companies/', {'q': 'acme'})
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['companies'][0]['name'], 'Acme')
        self.assertEqual(body['query'], 'acme')

    def test_company_list_hides_merged(self):
        target = make_company('Target')
        make_company('Loser', merged_into=target)
        resp = self.client.get(f'{self.API}/companies/')
        body = resp.json()
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(body['companies'][0]['name'], 'Target')

    # --- GET /api/vacancies/companies/{pk}/ ---

    def test_company_detail_is_public(self):
        company = make_company('Acme', reg_code='1234')
        vacancy = make_vacancy(1, company=company)
        CompanyAlias.objects.create(
            company=company, kind='name', value='Acme SIA',
            first_seen=timezone.now(), last_seen=timezone.now(),
        )
        resp = self.client.get(f'{self.API}/companies/{company.pk}/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['name'], 'Acme')
        self.assertEqual(body['reg_code'], '1234')
        self.assertEqual(body['name_aliases'], ['Acme SIA'])
        self.assertEqual(body['total_count'], 1)
        self.assertEqual(
            body['vacancies'][0]['id'], str(vacancy.pk)
        )

    def test_company_detail_merged_returns_canonical(self):
        target = make_company('Target')
        loser = make_company('Loser', merged_into=target)
        resp = self.client.get(f'{self.API}/companies/{loser.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], str(target.pk))

    def test_company_detail_404s_unknown_pk(self):
        import uuid
        resp = self.client.get(
            f'{self.API}/companies/{uuid.uuid4()}/'
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()['error'], 'not_found')

    # --- POST /api/vacancies/keywords/ ---

    def test_keywords_post_unauthenticated_401(self):
        resp = self.client.post(
            f'{self.API}/keywords/',
            data=json.dumps({'name': 'python'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body['error'], 'unauthenticated')
        # login_url points at the SPA page, not back at the JSON URL.
        self.assertIn(
            'next=%2Fvacancies%2Fkeywords%2F', body['login_url']
        )

    def test_keywords_post_success(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            f'{self.API}/keywords/',
            data=json.dumps(
                {'name': ' Python ', 'only_filter': False}
            ),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['success'])
        keyword = Keyword.objects.get()
        # KeywordForm keeps its strip+lowercase normalization.
        self.assertEqual(keyword.name, 'python')
        self.assertFalse(keyword.only_filter)

    def test_keywords_post_duplicate_400(self):
        Keyword.objects.create(name='python')
        self.client.force_login(self.user)
        resp = self.client.post(
            f'{self.API}/keywords/',
            data=json.dumps({'name': 'python'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['error'], 'bad_request')

    def test_keywords_post_invalid_422(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            f'{self.API}/keywords/',
            data=json.dumps({'name': ''}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['error'], 'validation_error')

    def test_keywords_post_csrf_enforced(self):
        csrf_client = self.client.__class__(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        resp = csrf_client.post(
            f'{self.API}/keywords/',
            data=json.dumps({'name': 'python'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()['error'], 'forbidden')


def refetch_detail(vacancy_id, **overrides):
    """Real-shaped detail-page payload — verified against
    props.pageProps.vacancy["1655039"] on cv.lv: the title lives
    under ``position``, salaries under ``highlights``, and the
    deadline/categories/keywords under ``settings`` (categories
    as enum names, keywords as {id, value} dicts)."""
    detail = employer_page_detail()
    detail.update({
        'position': 'Fresh python developer',
        'firstPublishDate': '2025-06-01',
        'highlights': {
            'address': 'Marijas iela 2a',
            'position': 'Fresh python developer',
            'salaryFrom': 3000,
            'salaryTo': 4500,
        },
        'settings': {
            'applyingUrl': 'https://ats.example/apply',
            'dateTo': '2026-01-15',
            'categories': ['INFORMATION_TECHNOLOGY'],
            'keywords': [{'id': 1, 'value': 'python'}],
        },
        'details': {
            'standardDetails': [
                {'title': 'About the job',
                 'content': '<p>more python here</p>'},
            ],
            'fileDetails': None,
        },
    })
    detail.update(overrides)
    payload = {
        'props': {
            'pageProps': {
                'vacancy': {str(vacancy_id): detail},
            },
        },
    }
    return response(next_data_html(payload))


class RefetchVacanciesTests(TestCase):
    """The refetch_vacancies command — no real HTTP: make_request
    is mocked at the class level, per-URL when needed."""

    def _run(self, *args, response_obj=None, responses=None,
             **kwargs):
        if responses is None:
            def responses(url, *a, **kw):
                return response_obj
        with mock.patch.object(
            VacancyScrapper, 'load_config', return_value=CONFIG
        ), mock.patch(
            'fetcher.management.commands.'
            'link_vacancies_to_companies.load_portals_config',
            return_value={'2': dict(CONFIG, order=1)},
        ), mock.patch.object(
            VacancyScrapper, 'make_request',
            side_effect=responses,
        ) as request:
            call_command('refetch_vacancies', *args, **kwargs)
        return request

    def _link(self, vacancy, keyword):
        return VacancyContainsKeyword.objects.create(
            vacancy=vacancy, keyword=keyword
        )

    def _fetched_urls(self, request):
        return [
            call.args[0] for call in request.call_args_list
        ]

    def test_keyword_id_selects_only_linked_vacancies(self):
        kw = Keyword.objects.create(name='python')
        linked = make_vacancy(1)
        self._link(linked, kw)
        make_vacancy(2)
        request = self._run(
            '--keyword-id', str(kw.id),
            response_obj=refetch_detail(1),
        )
        self.assertEqual(self._fetched_urls(request), [linked.url])

    def test_exclude_keywords_drops_matching_rows(self):
        kw = Keyword.objects.create(name='python')
        excluded = Keyword.objects.create(name='java')
        keep = make_vacancy(1)
        drop = make_vacancy(2)
        self._link(keep, kw)
        self._link(drop, kw)
        self._link(drop, excluded)
        request = self._run(
            '--keyword-id', str(kw.id),
            '--exclude-keywords', str(excluded.id),
            response_obj=refetch_detail(1),
        )
        self.assertEqual(self._fetched_urls(request), [keep.url])

    def test_ids_bypass_keyword_selection(self):
        kw = Keyword.objects.create(name='python')
        self._link(make_vacancy(1), kw)
        explicit = make_vacancy(2)  # no keyword links at all
        request = self._run(
            '--ids', '2',
            response_obj=refetch_detail(2),
        )
        urls = self._fetched_urls(request)
        self.assertEqual(urls, [explicit.url])

    def test_keyword_id_required_without_ids(self):
        with self.assertRaises(CommandError):
            self._run()

    def test_unknown_keyword_id_errors(self):
        with self.assertRaises(CommandError):
            self._run('--keyword-id', '999')
        kw = Keyword.objects.create(name='python')
        with self.assertRaises(CommandError):
            self._run(
                '--keyword-id', str(kw.id),
                '--exclude-keywords', '999',
            )

    def test_dry_run_fetches_and_writes_nothing(self):
        kw = Keyword.objects.create(name='python')
        vacancy = make_vacancy(1)
        self._link(vacancy, kw)
        out = io.StringIO()
        request = self._run(
            '--keyword-id', str(kw.id), '--dry-run', stdout=out,
        )
        request.assert_not_called()
        self.assertIn('dry-run', out.getvalue())
        vacancy.refresh_from_db()
        self.assertIsNone(vacancy.detail_fetched_at)
        self.assertFalse(Company.objects.exists())

    def test_refetch_updates_vacancy_and_company(self):
        python = Keyword.objects.create(name='python')
        java = Keyword.objects.create(name='java')
        vacancy = make_vacancy(
            42, title='Stale title',
            salary_from=111, salary_to=222,
        )
        self._link(vacancy, python)
        self._link(vacancy, java)
        self._run('--ids', '42', response_obj=refetch_detail(42))
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.title, 'Fresh python developer')
        self.assertEqual(vacancy.salary_from, 3000)
        self.assertEqual(vacancy.salary_to, 4500)
        # settings.dateTo is date-only — stored aware.
        self.assertFalse(
            timezone.is_naive(vacancy.application_deadline)
        )
        self.assertEqual(
            vacancy.application_deadline.date().isoformat(),
            '2026-01-15',
        )
        self.assertIsNotNone(vacancy.detail_fetched_at)
        # True refresh: the stale 'java' link is removed, the
        # still-matching 'python' link is kept.
        self.assertEqual(
            set(vacancy.keywords.values_list('name', flat=True)),
            {'python'},
        )
        company = Company.objects.get()
        self.assertEqual(vacancy.company_id, company.pk)
        self.assertEqual(company.name, 'Acme')
        self.assertEqual(company.about, 'About us')
        self.assertIsNotNone(company.detail_fetched_at)

    def test_expired_ad_is_counted_no_detail(self):
        vacancy = make_vacancy(42, title='Gone')
        out = io.StringIO()
        self._run(
            '--ids', '42',
            response_obj=response(
                next_data_html({'props': {'pageProps': {}}})
            ),
            stdout=out,
        )
        vacancy.refresh_from_db()
        self.assertIsNone(vacancy.detail_fetched_at)
        self.assertEqual(vacancy.title, 'Gone')
        self.assertIn('no_detail=1', out.getvalue())
        self.assertFalse(Company.objects.exists())

    def test_fetch_failure_leaves_row_untouched(self):
        vacancy = make_vacancy(42, title='Untouched')
        out = io.StringIO()
        self._run('--ids', '42', response_obj=None, stdout=out)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.title, 'Untouched')
        self.assertIsNone(vacancy.detail_fetched_at)
        self.assertIn('fetch_failed=1', out.getvalue())

    def test_no_ocr_skips_file_fetch(self):
        make_vacancy(42)
        detail_resp = refetch_detail(
            42,
            details={
                'standardDetails': [],
                'fileDetails': {'fileId': 'file-42'},
            },
        )
        request = self._run(
            '--ids', '42', '--no-ocr',
            response_obj=detail_resp,
        )
        # Only the detail page is fetched — the files-service
        # URL is never requested and no AI call happens.
        self.assertEqual(request.call_count, 1)
        self.assertFalse(VacancyFile.objects.exists())

    def test_ocr_text_feeds_keywords_and_saves_file(self):
        Keyword.objects.create(name='python')
        Keyword.objects.create(name='ocrword')
        vacancy = make_vacancy(42)
        detail_resp = refetch_detail(
            42,
            details={
                'standardDetails': [],
                'fileDetails': {'fileId': 'file-42'},
            },
        )

        def responses(url, *a, **kw):
            if 'files-service' in url:
                return response(b'IMG-BYTES', 'image/png')
            return detail_resp

        ai_client = mock.Mock()
        ai_client.generate.return_value = types.SimpleNamespace(
            text='has OCRWORD inside',
            served_model=None, ai_request=None,
        )
        with mock.patch(
            'fetcher.scraper.get_job_client',
            return_value=ai_client,
        ):
            self._run('--ids', '42', responses=responses)
        vacancy_file = VacancyFile.objects.get(file_id='file-42')
        vacancy.refresh_from_db()
        self.assertEqual(vacancy_file.vacancy_id, vacancy.pk)
        self.assertEqual(
            vacancy_file.extracted_text, 'has OCRWORD inside'
        )
        self.assertEqual(
            set(vacancy.keywords.values_list('name', flat=True)),
            {'python', 'ocrword'},
        )

    def test_absent_salary_or_categories_keeps_stored(self):
        """A detail payload that omits salary/categories must not
        wipe stored values — absent ≠ removed (key presence, not
        truthiness, allows a clear)."""
        industry = Industry.objects.create(name='it')
        vacancy = make_vacancy(
            42, salary_from=111, salary_to=222,
            application_deadline=timezone.now(),
        )
        VacancyIndustries.objects.create(
            vacancy=vacancy, industry=industry
        )
        detail = refetch_detail(
            42,
            highlights={
                'position': 'Fresh python developer',
            },
            settings={
                'applyingUrl': 'https://ats.example/apply',
            },
        )
        self._run('--ids', '42', response_obj=detail)
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.salary_from, 111)
        self.assertEqual(vacancy.salary_to, 222)
        self.assertIsNotNone(vacancy.application_deadline)
        self.assertEqual(
            set(
                vacancy.industries.values_list('name', flat=True)
            ),
            {'it'},
        )
        self.assertEqual(vacancy.title, 'Fresh python developer')

    def test_present_but_null_keys_clear_stored_values(self):
        vacancy = make_vacancy(
            42, salary_from=111, salary_to=222,
        )
        detail = refetch_detail(
            42,
            highlights={
                'position': 'Fresh python developer',
                'salaryFrom': None,
                'salaryTo': None,
            },
        )
        self._run('--ids', '42', response_obj=detail)
        vacancy.refresh_from_db()
        self.assertIsNone(vacancy.salary_from)
        self.assertIsNone(vacancy.salary_to)

    def test_no_employer_still_refreshes_vacancy(self):
        vacancy = make_vacancy(42, title='Stale title')
        out = io.StringIO()
        self._run(
            '--ids', '42',
            response_obj=refetch_detail(
                42, employerId=None, employer={},
            ),
            stdout=out,
        )
        vacancy.refresh_from_db()
        self.assertEqual(vacancy.title, 'Fresh python developer')
        self.assertIsNotNone(vacancy.detail_fetched_at)
        self.assertIsNone(vacancy.company_id)
        self.assertIn('no_employer=1', out.getvalue())
        self.assertFalse(Company.objects.exists())

    def test_limit_caps_processed_vacancies(self):
        kw = Keyword.objects.create(name='python')
        for portal_id in (1, 2, 3):
            self._link(make_vacancy(portal_id), kw)
        request = self._run(
            '--keyword-id', str(kw.id), '--limit', '2',
            response_obj=refetch_detail(1),
        )
        self.assertEqual(len(self._fetched_urls(request)), 2)

    def test_limit_must_be_positive(self):
        with self.assertRaises(CommandError):
            self._run('--ids', '1', '--limit', '0')

    def test_ids_rejects_keyword_selection_args(self):
        kw = Keyword.objects.create(name='python')
        with self.assertRaises(CommandError):
            self._run(
                '--ids', '1', '--keyword-id', str(kw.id)
            )
        with self.assertRaises(CommandError):
            self._run(
                '--ids', '1', '--exclude-keywords', str(kw.id)
            )

    def test_malformed_page_is_counted_no_next_data(self):
        make_vacancy(42)
        out = io.StringIO()
        self._run(
            '--ids', '42',
            response_obj=response(b'<html><p>oops</p></html>'),
            stdout=out,
        )
        self.assertIn('no_next_data=1', out.getvalue())
