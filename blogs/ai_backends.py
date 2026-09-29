"""Temporary AnalyzerBackend that calls the Gemini API directly.

Holds the model lists, retry loop, request cap and prompt assembly
moved out of ``BlogScraper._analyze_with_models`` (plus the PR-3 bug
fixes listed in plan section 2). Replaced by ``JobClientBackend`` in
PR-6.
"""

import logging
import time

from google import genai
from google.genai import errors as genai_errors

from .analyzer import AnalyzerResponse

logger = logging.getLogger('blogs')

MODELS_BY_ROLE = {
    'cheap': ['gemini-2.5-flash-lite'],
    'expensive': ['gemini-2.5-pro'],
}
RETRIES_PER_MODEL = 2

# Candidate finish_reason values meaning the output was filtered.
BLOCKED_FINISH_REASONS = frozenset({
    'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII',
})

# google-genai APIError codes a retry can never fix (e.g. bad key).
NON_RETRYABLE_CODES = frozenset({400, 401, 403, 404})


class MaxAPIRequestsReached(Exception):
    """Raised when the maximum number of API requests is reached."""
    pass


class APIRequestCounter:
    """Mutable per-run request counter.

    Shared between BlogScraper and its backend so the cap counts
    every attempt sent and ``scraper.api_request_count`` still works
    for the run-summary log.
    """

    def __init__(self, limit=None):
        self.count = 0
        self.limit = limit


def _reason_name(reason):
    """'SAFETY' for FinishReason.SAFETY / BlockReason values."""
    return getattr(reason, 'name', None) or str(reason)


class GeminiDirectBackend:
    """AnalyzerBackend talking to Gemini via the google-genai SDK."""

    def __init__(self, api_key, counter, logger=None):
        self.api_key = api_key
        self.counter = counter
        self.logger = logger or logging.getLogger('blogs')

    def generate(self, template_key, template_text, input_text, role):
        """Try each model of the role; AnalyzerResponse or None.

        Assembles the prompt as instructions + "\\n\\n---\\n\\n" +
        content, exactly as the scraper did. Returns None when every
        model failed; raises MaxAPIRequestsReached at the cap.
        """
        full_prompt = template_text + "\n\n---\n\n" + input_text
        client = genai.Client(api_key=self.api_key)

        for model_name in MODELS_BY_ROLE.get(role, []):
            for attempt in range(RETRIES_PER_MODEL):
                self._check_cap()
                self.logger.info(
                    f"Attempting model {model_name} for "
                    f"'{template_key}' (Attempt {attempt + 1}) "
                    f"[API calls: {self.counter.count}/"
                    f"{self.counter.limit or 'unlimited'}]"
                )
                try:
                    # The cap counts attempts sent — increment even
                    # when the call goes on to fail.
                    self.counter.count += 1
                    response = client.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                    )
                except Exception as e:
                    if self._is_non_retryable(e):
                        self.logger.warning(
                            "Model %s failed for '%s' with a "
                            "non-retryable error; moving to the next "
                            "model. Error: %s",
                            model_name, template_key, e
                        )
                        break
                    self.logger.warning(
                        "Model %s failed for '%s'. Retrying. "
                        "Error: %s",
                        model_name, template_key, e
                    )
                    time.sleep(2 ** (attempt + 1))
                    continue

                block_reason = self._block_reason(response)
                if block_reason:
                    self.logger.warning(
                        "Gemini API call blocked for '%s' with "
                        "reason: %s",
                        template_key, block_reason
                    )
                    return AnalyzerResponse(
                        text=None,
                        model_name=model_name,
                        blocked=True,
                        block_reason=block_reason,
                    )

                text = self._response_text(response)
                if not text:
                    # No text and not blocked — treat as a failed
                    # attempt instead of crashing the JSON parser.
                    self.logger.warning(
                        "Model %s returned no text for '%s'. "
                        "Retrying.",
                        model_name, template_key
                    )
                    time.sleep(2 ** (attempt + 1))
                    continue

                return AnalyzerResponse(text=text, model_name=model_name)

        self.logger.error(
            "Failed to get a valid response from Gemini API for '%s'.",
            template_key
        )
        return None

    def _check_cap(self):
        """Raise MaxAPIRequestsReached once the cap is hit."""
        if (self.counter.limit is not None and
                self.counter.count >= self.counter.limit):
            self.logger.warning(
                "Reached max API requests limit "
                f"({self.counter.limit}). Stopping scraper."
            )
            raise MaxAPIRequestsReached(
                f"Reached limit of {self.counter.limit} API requests"
            )

    def _block_reason(self, response):
        """Return a block reason string, or None when not blocked.

        Detects prompt-level blocks (prompt_feedback.block_reason)
        and candidate-level safety finishes — the latter used to slip
        through and crash downstream on response.text being None.
        """
        feedback = getattr(response, 'prompt_feedback', None)
        reason = getattr(feedback, 'block_reason', None)
        if reason:
            return _reason_name(reason)

        candidates = getattr(response, 'candidates', None) or []
        if candidates:
            finish = getattr(candidates[0], 'finish_reason', None)
            name = _reason_name(finish) if finish else ''
            if name in BLOCKED_FINISH_REASONS:
                return name

        return None

    def _response_text(self, response):
        """response.text, None-safe (can be None/raise on blocked or
        empty candidates)."""
        try:
            return response.text
        except Exception:
            return None

    def _is_non_retryable(self, error):
        """True for API errors no retry can fix (e.g. invalid key)."""
        return (
            isinstance(error, genai_errors.APIError) and
            error.code in NON_RETRYABLE_CODES
        )
