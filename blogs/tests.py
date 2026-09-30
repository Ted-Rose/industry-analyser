"""Tests for ThemeAnalyzer (PR-3) and the JobClient wiring (PR-6).

Backend-mapping tests use a stub client (SimpleTestCase — no DB).
Integration tests drive the real JobClient with a fake provider
injected into PROVIDER_CLASSES — no network, no API keys.
"""

import logging
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from ai_providers import errors
from ai_providers.client import get_job_client
from ai_providers.jobs import ensure_job
from ai_providers.models import (
    AIInput,
    AIModel,
    AIPromptTemplate,
    AIRequest,
)
from ai_providers.providers import PROVIDER_CLASSES
from ai_providers.providers.base import BaseAIProvider
from ai_providers.types import AIResponse, GenerationOptions, PromptSpec

from blogs.ai_backends import JobClientBackend, MaxAPIRequestsReached
from blogs.ai_jobs import THEME_ANALYSIS
from blogs.analyzer import (
    AnalyzerResponse,
    ThemeAnalyzer,
    load_theme_prompt,
)
from blogs.models import PageAnalysis, Theme
from blogs.scraper import BlogScraper

logger = logging.getLogger('blogs')


def theme(name):
    """Minimal stand-in for Theme (analyse() only needs .name)."""
    return SimpleNamespace(name=name)


def response(text, model_name='fake-model', **kwargs):
    return AnalyzerResponse(text=text, model_name=model_name, **kwargs)


class FakeBackend:
    """AnalyzerBackend stub: records calls, replays canned outcomes.

    ``outcomes`` maps ``(role, template_key)`` to an AnalyzerResponse
    to return or an Exception to raise. A missing key means "every
    model failed" (returns None).
    """

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []

    def generate(self, template_key, template_text, input_text, role):
        self.calls.append({
            'template_key': template_key,
            'template_text': template_text,
            'input_text': input_text,
            'role': role,
        })
        outcome = self.outcomes.get((role, template_key))
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def roles_called(backend):
    return [c['role'] for c in backend.calls]


class ThemeAnalyzerTests(SimpleTestCase):
    """One test per preserved behavior in plan section 5.6."""

    def setUp(self):
        self.themes = [theme('violence'), theme('sexual')]
        self.prompts = {
            t.name: f'instructions for {t.name}' for t in self.themes
        }

    def analyzer(self, backend, prompts=None):
        prompts = self.prompts if prompts is None else prompts
        return ThemeAnalyzer(
            backend, lambda name: prompts.get(name), logger
        )

    # 5.6.1 — cheap pass returns after the FIRST theme that yields a
    # parsed result, regardless of match; failures are skipped.
    def test_cheap_pass_returns_after_first_parsed_theme(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(
                '{"violence": false, "confidence_score": 0.1,'
                ' "reasoning_summary": "fine"}'
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=True
        )
        self.assertEqual(roles_called(backend), [
            'cheap',                    # violence parsed -> return
            'expensive', 'expensive',   # no match -> expensive pass
        ])
        self.assertIsNone(result)  # nothing parsed on expensive pass

    def test_cheap_pass_skips_failed_themes_and_continues(self):
        themes = [
            theme('missing'), theme('fails'),
            theme('badjson'), theme('violence'),
        ]
        prompts = {
            t.name: f'instructions for {t.name}' for t in themes
        }
        del prompts['missing']  # missing prompt file
        backend = FakeBackend({
            ('cheap', 'blogs.theme.fails'): None,  # all models failed
            ('cheap', 'blogs.theme.badjson'): response('{not json'),
            ('cheap', 'blogs.theme.violence'): response(
                '{"violence": true, "confidence_score": 0.9,'
                ' "reasoning_summary": "bad"}'
            ),
        })
        result = self.analyzer(backend, prompts).analyse(
            'content', themes, use_cheap_tier=True
        )
        self.assertEqual(
            [c['template_key'] for c in backend.calls],
            ['blogs.theme.fails', 'blogs.theme.badjson',
             'blogs.theme.violence'],
        )
        self.assertTrue(result['violence']['violence'])

    # 5.6.2 — a cheap result with a theme match returns cheap results.
    def test_cheap_match_returns_cheap_results(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(
                '{"violence": true, "confidence_score": 0.8,'
                ' "reasoning_summary": "bad"}',
                model_name='cheap-1',
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=True
        )
        self.assertEqual(roles_called(backend), ['cheap'])
        self.assertEqual(result['violence']['model'], 'cheap-1')
        self.assertEqual(result['violence']['model_tier'], 'cheap')
        self.assertTrue(result['violence']['violence'])

    # 5.6.3 — otherwise the expensive pass covers all themes, returns
    # at the first match and discards the cheap results.
    def test_no_cheap_match_runs_expensive_and_discards_cheap(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(
                '{"violence": false}', model_name='cheap-1'
            ),
            ('expensive', 'blogs.theme.violence'): response(
                '{"violence": false}', model_name='exp-1'
            ),
            ('expensive', 'blogs.theme.sexual'): response(
                '{"sexual": true}', model_name='exp-1'
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=True
        )
        self.assertEqual(
            roles_called(backend),
            ['cheap', 'expensive', 'expensive'],
        )
        # 'violence' comes from the expensive pass — cheap discarded.
        self.assertEqual(result['violence']['model'], 'exp-1')
        self.assertEqual(result['violence']['model_tier'], 'expensive')
        self.assertTrue(result['sexual']['sexual'])

    def test_use_cheap_tier_false_runs_expensive_only(self):
        backend = FakeBackend({
            ('expensive', 'blogs.theme.violence'): response(
                '{"violence": true}', model_name='exp-1'
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=False
        )
        self.assertEqual(roles_called(backend), ['expensive'])
        self.assertTrue(result['violence']['violence'])

    # 5.6.4 — blocked returns the synthetic result immediately.
    def test_blocked_returns_synthetic_result_immediately(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(
                None, model_name='cheap-1',
                blocked=True, block_reason='SAFETY',
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=True
        )
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(result, {
            'violence': {
                'violence': True,
                'confidence_score': 1.0,
                'reasoning_summary': (
                    'Content analysis blocked by API safety filters. '
                    'Reason: SAFETY'
                ),
                'model': 'cheap-1',
                'model_tier': 'cheap',
                'blocked': True,
            },
        })

    # 5.6.5 — JSON cleanup strips fences and trailing commas; None or
    # empty text never crashes.
    def test_json_cleanup_fences_and_trailing_commas(self):
        text = (
            '```json\n{"violence": true, "confidence_score": 0.9,'
            ' "reasoning_summary": "x",}\n```'
        )
        backend = FakeBackend({
            ('expensive', 'blogs.theme.violence'): response(text),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=False
        )
        self.assertTrue(result['violence']['violence'])
        self.assertEqual(result['violence']['confidence_score'], 0.9)

    def test_none_and_empty_text_never_crash(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(None),
            ('cheap', 'blogs.theme.sexual'): response('   '),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=True
        )
        self.assertIsNone(result)
        self.assertEqual(roles_called(backend), [
            'cheap', 'cheap',           # both skipped (unparsable)
            'expensive', 'expensive',
        ])

    # 5.6.6 — results are stamped with model/model_tier plus the
    # backend's extra keys.
    def test_result_stamped_with_model_tier_and_extra(self):
        backend = FakeBackend({
            ('expensive', 'blogs.theme.violence'): response(
                '{"violence": true}', model_name='exp-1',
                extra={'ai_request_id': 42},
            ),
        })
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=False
        )
        entry = result['violence']
        self.assertEqual(entry['model'], 'exp-1')
        self.assertEqual(entry['model_tier'], 'expensive')
        self.assertEqual(entry['ai_request_id'], 42)

    # 5.6.7 — no parsed result at all -> None.
    def test_no_parsed_result_returns_none(self):
        backend = FakeBackend()  # every theme fails
        result = self.analyzer(backend).analyse(
            'content', self.themes, use_cheap_tier=False
        )
        self.assertIsNone(result)

    # 5.6.8 — instructions and content reach the backend separately.
    def test_backend_receives_instructions_and_content_separately(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'): response(
                '{"violence": true}'
            ),
        })
        self.analyzer(backend).analyse(
            'ARTICLE BODY', self.themes, use_cheap_tier=True
        )
        call = backend.calls[0]
        self.assertEqual(call['template_key'], 'blogs.theme.violence')
        self.assertEqual(
            call['template_text'], 'instructions for violence'
        )
        self.assertEqual(call['input_text'], 'ARTICLE BODY')
        self.assertEqual(call['role'], 'cheap')

    def test_max_api_requests_reached_propagates(self):
        backend = FakeBackend({
            ('cheap', 'blogs.theme.violence'):
                MaxAPIRequestsReached('cap hit'),
        })
        with self.assertRaises(MaxAPIRequestsReached):
            self.analyzer(backend).analyse(
                'content', self.themes, use_cheap_tier=True
            )


class LoadThemePromptTests(SimpleTestCase):
    """prompt_loader reads blogs/prompts/<theme>.txt (5.6.8)."""

    def test_existing_prompt_returns_text(self):
        text = load_theme_prompt('violence')
        self.assertIsInstance(text, str)
        self.assertTrue(text.strip())

    def test_missing_prompt_returns_none(self):
        self.assertIsNone(load_theme_prompt('no-such-theme-xyz'))


class BlogScraperAnalyseContentTests(SimpleTestCase):
    """BlogScraper.analyse_content delegates to its ThemeAnalyzer.

    __init__ needs the DB and config.yaml, so the tests build a bare
    instance and wire _analyzer / ai_client directly.
    """

    def _scraper(self, backend, client=None):
        scraper = BlogScraper.__new__(BlogScraper)
        scraper.ai_client = client or SimpleNamespace(request_count=0)
        scraper._analyzer = ThemeAnalyzer(
            backend, lambda name: 'instructions', logger
        )
        return scraper

    def test_delegates_with_url_cheap_tier_flag(self):
        analyzer = mock.Mock()
        analyzer.analyse.return_value = {'violence': {}}
        scraper = BlogScraper.__new__(BlogScraper)
        scraper._analyzer = analyzer
        scraper.current_url_use_cheap_tier = False
        themes = [theme('violence')]

        result = scraper.analyse_content('content', themes)

        analyzer.analyse.assert_called_once_with(
            'content', themes, use_cheap_tier=False
        )
        self.assertEqual(result, {'violence': {}})

    def test_delegates_default_cheap_tier(self):
        # current_url_use_cheap_tier unset -> True, as before.
        analyzer = mock.Mock()
        analyzer.analyse.return_value = None
        scraper = BlogScraper.__new__(BlogScraper)
        scraper._analyzer = analyzer

        scraper.analyse_content('content', [])

        analyzer.analyse.assert_called_once_with(
            'content', [], use_cheap_tier=True
        )

    def test_url_flag_controls_tier_end_to_end(self):
        backend = FakeBackend({
            ('expensive', 'blogs.theme.violence'): response(
                '{"violence": true}', model_name='exp-1'
            ),
        })
        scraper = self._scraper(backend)
        scraper.current_url_use_cheap_tier = False

        result = scraper.analyse_content('content', [theme('violence')])

        self.assertEqual(roles_called(backend), ['expensive'])
        self.assertTrue(result['violence']['violence'])

    def test_api_request_count_is_client_request_count(self):
        scraper = BlogScraper.__new__(BlogScraper)
        scraper.ai_client = SimpleNamespace(request_count=7)

        self.assertEqual(scraper.api_request_count, 7)


class StubClient:
    """JobClient stand-in for JobClientBackend mapping tests.

    ``outcome`` is an AIResult-shaped object to return or an
    Exception to raise from generate().
    """

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []
        self.request_count = 0

    def generate(self, spec, role, options):
        self.calls.append(
            {'spec': spec, 'role': role, 'options': options}
        )
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def ai_result(text='ok', status='success', block_reason=None,
              model_pk=11, model_name='m1', request_pk=22):
    """AIResult-shaped stand-in (SimpleTestCase, no DB rows)."""
    return SimpleNamespace(
        text=text,
        status=status,
        block_reason=block_reason,
        served_model=SimpleNamespace(pk=model_pk, name=model_name),
        ai_request=SimpleNamespace(pk=request_pk),
    )


class JobClientBackendTests(SimpleTestCase):
    """JobClientBackend maps JobClient outcomes onto AnalyzerBackend
    (PR-6): AIRequestCapReached -> MaxAPIRequestsReached,
    AIAllModelsFailedError -> None, ids go to extra."""

    def test_success_returns_response_with_extra_ids(self):
        client = StubClient(ai_result(text='{"violence": true}'))
        backend = JobClientBackend(client, logger)

        resp = backend.generate(
            'blogs.theme.violence', 'instr', 'content', 'cheap'
        )

        self.assertEqual(resp.text, '{"violence": true}')
        self.assertEqual(resp.model_name, 'm1')
        self.assertFalse(resp.blocked)
        self.assertIsNone(resp.block_reason)
        self.assertEqual(
            resp.extra, {'ai_model_id': 11, 'ai_request_id': 22}
        )

    def test_builds_prompt_spec_inline_v1_with_role_and_options(self):
        client = StubClient(ai_result())
        backend = JobClientBackend(client, logger)

        backend.generate('key.t', 'INSTR', 'INPUT', 'expensive')

        call = client.calls[0]
        self.assertEqual(call['spec'], PromptSpec(
            template_key='key.t',
            template_text='INSTR',
            input_text='INPUT',
            layout='inline_v1',
        ))
        self.assertEqual(call['role'], 'expensive')
        self.assertEqual(call['options'], GenerationOptions())

    def test_cap_reached_maps_to_max_api_requests_reached(self):
        client = StubClient(errors.AIRequestCapReached('cap'))
        backend = JobClientBackend(client, logger)

        with self.assertRaises(MaxAPIRequestsReached):
            backend.generate('key.t', 'i', 'c', 'cheap')

    def test_all_models_failed_returns_none(self):
        client = StubClient(errors.AIAllModelsFailedError('all bad'))
        backend = JobClientBackend(client, logger)

        resp = backend.generate('key.t', 'i', 'c', 'cheap')

        self.assertIsNone(resp)

    def test_blocked_maps_to_blocked_response_with_ids(self):
        client = StubClient(ai_result(
            text=None, status='blocked', block_reason='SAFETY',
        ))
        backend = JobClientBackend(client, logger)

        resp = backend.generate('key.t', 'i', 'c', 'cheap')

        self.assertTrue(resp.blocked)
        self.assertEqual(resp.block_reason, 'SAFETY')
        self.assertEqual(resp.model_name, 'm1')
        self.assertEqual(
            resp.extra, {'ai_model_id': 11, 'ai_request_id': 22}
        )

    def test_job_errors_propagate_unchanged(self):
        # Not-configured/disabled jobs stop the caller (no mapping).
        client = StubClient(errors.AIJobNotConfiguredError('no role'))
        backend = JobClientBackend(client, logger)

        with self.assertRaises(errors.AIJobNotConfiguredError):
            backend.generate('key.t', 'i', 'c', 'cheap')


class FakeGeminiProvider(BaseAIProvider):
    """Scripted provider adapter (pattern from ai_providers tests).

    ``script`` maps model name -> a list of AIResponse/exception
    outcomes consumed one per call; an empty/missing entry returns a
    generic success.
    """

    provider_type = 'gemini'
    script = {}
    calls = []

    def generate(self, model, prompt, options):
        type(self).calls.append(
            {'model': model, 'prompt': prompt, 'options': options}
        )
        queue = type(self).script.get(model) or []
        outcome = (
            queue.pop(0) if queue
            else AIResponse(text='ok', served_model=model)
        )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @classmethod
    def called_models(cls):
        return [call['model'] for call in cls.calls]


@override_settings(GEMINI_API_KEY='test-key')
@mock.patch('time.sleep', lambda *args, **kwargs: None)
class JobClientIntegrationTests(TestCase):
    """ThemeAnalyzer -> JobClientBackend -> real JobClient -> fake
    provider. Exercises THEME_ANALYSIS seeding and prompt storage."""

    THEMES = ('violence', 'sexual', 'insult')

    def setUp(self):
        super().setUp()
        FakeGeminiProvider.script = {}
        FakeGeminiProvider.calls = []
        patcher = mock.patch.dict(
            PROVIDER_CLASSES, {'gemini': FakeGeminiProvider}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job = ensure_job(THEME_ANALYSIS)

    def job_client(self, **kwargs):
        """A JobClient over the setUp job (self.client stays the
        Django test client)."""
        return get_job_client(self.job, **kwargs)

    def analyzer(self):
        return ThemeAnalyzer(
            backend=JobClientBackend(self.job_client(), logger),
            prompt_loader=lambda name: f'instructions for {name}',
            logger=logger,
        )

    def test_ensure_job_seeds_gemini_assignments(self):
        self.assertEqual(self.job.slug, 'blogs.theme_analysis')
        self.assertEqual(self.job.declared_roles, ['cheap', 'expensive'])
        cheap = self.job.assignments.get(role='cheap')
        expensive = self.job.assignments.get(role='expensive')
        self.assertEqual(cheap.model.name, 'gemini-2.5-flash-lite')
        self.assertEqual(expensive.model.name, 'gemini-2.5-pro')
        self.assertEqual(cheap.model.provider.slug, 'gemini')

    def test_three_themes_one_input_three_templates(self):
        themes = [theme(name) for name in self.THEMES]
        FakeGeminiProvider.script = {
            'gemini-2.5-pro': [
                AIResponse(
                    text=(
                        '{"violence": false, "sexual": false,'
                        ' "insult": false, "confidence_score": 0.1,'
                        ' "reasoning_summary": "fine"}'
                    ),
                    served_model='gemini-2.5-pro',
                ),
            ] * 3,
        }

        result = self.analyzer().analyse(
            'article body', themes, use_cheap_tier=False
        )

        self.assertEqual(set(result), set(self.THEMES))
        self.assertEqual(
            FakeGeminiProvider.called_models(),
            ['gemini-2.5-pro'] * 3,
        )
        self.assertEqual(AIRequest.objects.count(), 3)
        self.assertEqual(AIInput.objects.count(), 1)
        self.assertEqual(AIPromptTemplate.objects.count(), 3)
        self.assertEqual(
            set(AIPromptTemplate.objects.values_list('key', flat=True)),
            {f'blogs.theme.{name}' for name in self.THEMES},
        )
        for request in AIRequest.objects.all():
            self.assertEqual(request.prompt_layout, 'inline_v1')
            self.assertEqual(request.role, 'expensive')
            self.assertIsNotNone(request.input_id)
            self.assertIsNotNone(request.prompt_template_id)
            self.assertIsNotNone(request.rendered_prompt())

    def test_cli_override_wins_when_lower(self):
        # The AIJob row caps at 10/run; the CLI override (1) is lower
        # and wins — JobClient raises AIRequestCapReached, mapped to
        # MaxAPIRequestsReached by the backend.
        self.job.max_requests_per_run = 10
        self.job.save()
        backend = JobClientBackend(
            self.job_client(max_requests_per_run=1), logger
        )

        resp = backend.generate('key.t', 'i', 'c', 'expensive')
        self.assertIsNotNone(resp)
        with self.assertRaises(MaxAPIRequestsReached):
            backend.generate('key.t', 'i', 'c', 'expensive')

    def test_cli_override_higher_than_db_cap_loses(self):
        self.job.max_requests_per_run = 1
        self.job.save()
        backend = JobClientBackend(
            self.job_client(max_requests_per_run=10), logger
        )

        backend.generate('key.t', 'i', 'c', 'expensive')
        with self.assertRaises(MaxAPIRequestsReached):
            backend.generate('key.t', 'i', 'c', 'expensive')


@override_settings(GEMINI_API_KEY='test-key')
@mock.patch('time.sleep', lambda *args, **kwargs: None)
class PageAnalysisAISaveTests(TestCase):
    """analyse_and_save_resource stamps PageAnalysis with the AI FKs.

    PENDING MIGRATION: these need the blogs migration adding
    PageAnalysis.ai_model/ai_request columns to the test DB.
    """

    def setUp(self):
        super().setUp()
        FakeGeminiProvider.script = {}
        FakeGeminiProvider.calls = []
        patcher = mock.patch.dict(
            PROVIDER_CLASSES, {'gemini': FakeGeminiProvider}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job = ensure_job(THEME_ANALYSIS)
        self.job_client = get_job_client(self.job)
        for order, name in enumerate(('violence', 'sexual', 'insult')):
            Theme.objects.create(name=name, analysis_order=order)

    def _scraper(self):
        """Bare BlogScraper wired like __init__ leaves it (avoids the
        gitignored config.yaml dependency)."""
        scraper = BlogScraper.__new__(BlogScraper)
        scraper.config = {}
        scraper.target_theme = None
        scraper.reanalyze = False
        scraper.max_api_requests = None
        scraper.current_url_use_cheap_tier = False
        scraper.ai_client = self.job_client
        scraper._analyzer = ThemeAnalyzer(
            backend=JobClientBackend(self.job_client, logger),
            prompt_loader=lambda name: f'instructions for {name}',
            logger=logger,
        )
        return scraper

    @staticmethod
    def _page_data(url, **overrides):
        data = {
            'url': url,
            'title': 'a page',
            'content': 'article body text',
            'has_video': False,
            'video_count': 0,
            'image_count': 0,
            'text_length': 2000,
        }
        data.update(overrides)
        return data

    def test_saved_analyses_have_ai_model_and_request_fks(self):
        FakeGeminiProvider.script = {
            'gemini-2.5-pro': [
                AIResponse(
                    text=(
                        '{"violence": false, "sexual": false,'
                        ' "insult": false, "confidence_score": 0.1,'
                        ' "reasoning_summary": "fine"}'
                    ),
                    served_model='gemini-2.5-pro',
                ),
            ] * 3,
        }
        scraper = self._scraper()
        url = 'http://example.com/p1'
        scraper.extract_resource = (
            lambda href, resp: self._page_data(url)
        )

        page = scraper.analyse_and_save_resource(object(), url)

        self.assertIsNotNone(page)
        served = AIModel.objects.get(name='gemini-2.5-pro')
        analyses = PageAnalysis.objects.filter(page=page)
        self.assertEqual(analyses.count(), 3)
        for analysis in analyses:
            self.assertEqual(analysis.ai_model_id, served.pk)
            self.assertIsNotNone(analysis.ai_request_id)
            self.assertEqual(analysis.ai_request.served_model, served)
            self.assertEqual(analysis.model, 'gemini-2.5-pro')
            self.assertEqual(analysis.model_tier, 'expensive')
            self.assertFalse(analysis.theme_match)

    def test_content_analyzer_row_keeps_null_fks(self):
        kid_theme = Theme.objects.create(
            name='kid_unfriendly', analysis_order=9
        )
        scraper = self._scraper()
        url = 'http://example.com/media'
        scraper.extract_resource = (
            lambda href, resp: self._page_data(
                url, has_video=True, video_count=2, text_length=10
            )
        )

        page = scraper.analyse_and_save_resource(object(), url)

        analysis = PageAnalysis.objects.get(page=page, theme=kid_theme)
        self.assertEqual(analysis.model, 'content_analyzer')
        self.assertIsNone(analysis.ai_model_id)
        self.assertIsNone(analysis.ai_request_id)


class ScrapeBlogsCommandTests(SimpleTestCase):
    """The --max-api-requests CLI override reaches BlogScraper."""

    @mock.patch('blogs.management.commands.scrape_blogs.BlogScraper')
    def test_max_api_requests_passed_to_scraper(self, scraper_cls):
        call_command('scrape_blogs', '--max-api-requests', '3')

        scraper_cls.assert_called_once_with(
            target_theme=None,
            reanalyze=False,
            max_api_requests=3,
        )

    @mock.patch('blogs.management.commands.scrape_blogs.BlogScraper')
    def test_max_api_requests_defaults_to_none(self, scraper_cls):
        call_command('scrape_blogs')

        scraper_cls.assert_called_once_with(
            target_theme=None,
            reanalyze=False,
            max_api_requests=None,
        )
