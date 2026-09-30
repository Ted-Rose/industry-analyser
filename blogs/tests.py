"""Tests for the ThemeAnalyzer extraction (PR-3, plan section 5.6).

All backends are fakes or fully mocked — no network, no API keys, no
DB access (SimpleTestCase only; themes are simple ``.name`` stubs).
"""

import logging
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from blogs.ai_backends import (
    APIRequestCounter,
    GeminiDirectBackend,
    MaxAPIRequestsReached,
)
from blogs.analyzer import (
    AnalyzerResponse,
    ThemeAnalyzer,
    load_theme_prompt,
)
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


class CountingBackend:
    """Fake backend that bumps the shared counter on every call."""

    def __init__(self, counter, outcome):
        self.counter = counter
        self.outcome = outcome

    def generate(self, template_key, template_text, input_text, role):
        self.counter.count += 1
        return self.outcome


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
    instance and wire _analyzer / _request_counter directly.
    """

    def _scraper(self, backend, counter=None):
        scraper = BlogScraper.__new__(BlogScraper)
        scraper._request_counter = counter or APIRequestCounter()
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

    def test_api_request_count_reflects_backend_attempts(self):
        counter = APIRequestCounter()
        backend = CountingBackend(
            counter, response('{"violence": true}')
        )
        scraper = self._scraper(backend, counter)
        scraper.current_url_use_cheap_tier = True

        self.assertEqual(scraper.api_request_count, 0)
        scraper.analyse_content('content', [theme('violence')])
        self.assertEqual(scraper.api_request_count, 1)


class GeminiDirectBackendTests(SimpleTestCase):
    """The moved Gemini loop, incl. the PR-3 bug fixes."""

    def _backend(self, counter=None):
        return GeminiDirectBackend(
            api_key='test-key',
            counter=counter or APIRequestCounter(),
            logger=logger,
        )

    def _response(self, text='{"violence": true}', block_reason=None,
                  finish_reason=None, candidates=None):
        if candidates is None:
            candidates = [SimpleNamespace(finish_reason=finish_reason)]
        feedback = (
            SimpleNamespace(block_reason=block_reason)
            if block_reason else None
        )
        return SimpleNamespace(
            text=text, prompt_feedback=feedback, candidates=candidates
        )

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_success_assembles_prompt_and_returns_text(
            self, client_cls, _sleep):
        client = client_cls.return_value
        client.models.generate_content.return_value = self._response()

        resp = self._backend().generate(
            'blogs.theme.violence', 'instr', 'content', 'cheap'
        )

        self.assertEqual(resp.text, '{"violence": true}')
        self.assertEqual(resp.model_name, 'gemini-2.5-flash-lite')
        self.assertFalse(resp.blocked)
        client.models.generate_content.assert_called_once_with(
            model='gemini-2.5-flash-lite',
            contents='instr\n\n---\n\ncontent',
        )

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_cap_raises_before_sending(self, client_cls, _sleep):
        counter = APIRequestCounter(limit=1)
        counter.count = 1
        client = client_cls.return_value

        with self.assertRaises(MaxAPIRequestsReached):
            self._backend(counter).generate(
                'blogs.theme.violence', 'i', 'c', 'cheap'
            )
        client.models.generate_content.assert_not_called()

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_failed_attempts_count_toward_cap(self, client_cls, _sleep):
        counter = APIRequestCounter(limit=1)
        client = client_cls.return_value
        client.models.generate_content.side_effect = Exception('boom')

        with self.assertRaises(MaxAPIRequestsReached):
            self._backend(counter).generate(
                'blogs.theme.violence', 'i', 'c', 'cheap'
            )
        # One failed attempt was sent and counted; the cap then fired.
        self.assertEqual(counter.count, 1)
        self.assertEqual(
            client.models.generate_content.call_count, 1
        )

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_all_models_failed_returns_none(self, client_cls, _sleep):
        counter = APIRequestCounter()
        client = client_cls.return_value
        client.models.generate_content.side_effect = Exception('boom')

        resp = self._backend(counter).generate(
            'blogs.theme.violence', 'i', 'c', 'cheap'
        )

        self.assertIsNone(resp)
        self.assertEqual(counter.count, 2)  # both retries counted

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_prompt_level_block(self, client_cls, _sleep):
        client = client_cls.return_value
        client.models.generate_content.return_value = self._response(
            text=None, block_reason='PROHIBITED_CONTENT'
        )

        resp = self._backend().generate(
            'blogs.theme.violence', 'i', 'c', 'cheap'
        )

        self.assertTrue(resp.blocked)
        self.assertEqual(resp.block_reason, 'PROHIBITED_CONTENT')
        self.assertEqual(resp.model_name, 'gemini-2.5-flash-lite')

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_candidate_level_safety_block(self, client_cls, _sleep):
        client = client_cls.return_value
        client.models.generate_content.return_value = self._response(
            text=None,
            finish_reason=genai_types.FinishReason.SAFETY,
        )

        resp = self._backend().generate(
            'blogs.theme.violence', 'i', 'c', 'cheap'
        )

        self.assertTrue(resp.blocked)
        self.assertEqual(resp.block_reason, 'SAFETY')

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_empty_text_retried_then_none(self, client_cls, _sleep):
        counter = APIRequestCounter()
        client = client_cls.return_value
        client.models.generate_content.return_value = self._response(
            text=None
        )

        resp = self._backend(counter).generate(
            'blogs.theme.violence', 'i', 'c', 'cheap'
        )

        self.assertIsNone(resp)
        self.assertEqual(
            client.models.generate_content.call_count, 2
        )
        self.assertEqual(counter.count, 2)

    @mock.patch('blogs.ai_backends.time.sleep')
    @mock.patch('blogs.ai_backends.genai.Client')
    def test_non_retryable_error_skips_retries(self, client_cls, _sleep):
        counter = APIRequestCounter()
        client = client_cls.return_value
        client.models.generate_content.side_effect = (
            genai_errors.APIError(
                code=401,
                response_json={'error': {'message': 'bad key'}},
            )
        )

        resp = self._backend(counter).generate(
            'blogs.theme.violence', 'i', 'c', 'cheap'
        )

        self.assertIsNone(resp)
        self.assertEqual(
            client.models.generate_content.call_count, 1
        )
        self.assertEqual(counter.count, 1)
