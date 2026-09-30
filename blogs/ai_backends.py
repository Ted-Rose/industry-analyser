"""AnalyzerBackend backed by the ai_providers JobClient (PR-6).

Model lists, retries, fallbacks, request caps and AIRequest logging
live in ``ai_providers.client.JobClient`` — the DB (AIJob/AIJobModel
assignments) is the source of truth for which models each role uses.
This adapter only translates between the ThemeAnalyzer backend
protocol (``blogs/analyzer.py``) and the ai_providers types/errors.
"""

import logging

from ai_providers.errors import (
    AIAllModelsFailedError,
    AIRequestCapReached,
)
from ai_providers.types import GenerationOptions, PromptSpec

from .analyzer import AnalyzerResponse

logger = logging.getLogger('blogs')


class MaxAPIRequestsReached(Exception):
    """Raised when the maximum number of API requests is reached."""
    pass


class JobClientBackend:
    """AnalyzerBackend that sends prompts through a JobClient."""

    def __init__(self, client, logger=None):
        self.client = client
        self.logger = logger or logging.getLogger('blogs')

    def generate(self, template_key, template_text, input_text, role):
        """Send one (theme, role) generation via the JobClient.

        Returns an ``AnalyzerResponse`` on success/blocked and None
        when every assigned model failed. ``AIRequestCapReached`` is
        re-raised as ``MaxAPIRequestsReached`` so the scraper stops
        with its existing cost-control flow.
        """
        spec = PromptSpec(
            template_key=template_key,
            template_text=template_text,
            input_text=input_text,
            layout='inline_v1',
        )
        try:
            result = self.client.generate(
                spec, role=role, options=GenerationOptions()
            )
        except AIRequestCapReached as e:
            raise MaxAPIRequestsReached(str(e)) from e
        except AIAllModelsFailedError as e:
            self.logger.error(
                "All assigned models failed for '%s' (role '%s'): %s",
                template_key, role, e
            )
            return None

        return AnalyzerResponse(
            text=result.text,
            model_name=result.served_model.name,
            blocked=result.status == 'blocked',
            block_reason=result.block_reason,
            extra={
                'ai_model_id': result.served_model.pk,
                'ai_request_id': result.ai_request.pk,
            },
        )
