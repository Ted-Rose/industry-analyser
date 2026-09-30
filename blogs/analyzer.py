"""Theme analysis orchestration for the blogs scraper (plan 5.6).

Pure orchestration — no vendor SDK code, no DB access. The backend
(`JobClientBackend`, blogs/ai_backends.py) hands generation to the
ai_providers JobClient, which owns the model assignments, retries,
request caps and prompt rendering; the analyzer passes instructions
and content to it separately.
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol

from django.conf import settings


@dataclass
class AnalyzerResponse:
    """One backend result for a single (theme, role) generation."""
    text: str | None
    model_name: str
    blocked: bool = False
    block_reason: str | None = None
    extra: dict = field(default_factory=dict)  # merged into result


class AnalyzerBackend(Protocol):
    """Backend interface consumed by ThemeAnalyzer."""

    def generate(self, template_key: str, template_text: str,
                 input_text: str, role: str) -> AnalyzerResponse | None:
        """Generate one analysis for (template_key, role).

        Returns None when every model failed. May raise
        ``MaxAPIRequestsReached`` (blogs/ai_backends.py) when the
        per-run request cap is hit.
        """
        ...


def theme_prompt_path(theme_name):
    """Absolute path of blogs/prompts/<theme_name>.txt."""
    return os.path.join(
        settings.BASE_DIR, 'blogs', 'prompts', f'{theme_name}.txt'
    )


def load_theme_prompt(theme_name):
    """Read blogs/prompts/<theme_name>.txt; None when missing."""
    try:
        with open(theme_prompt_path(theme_name), 'r') as file:
            return file.read()
    except FileNotFoundError:
        return None


class ThemeAnalyzer:
    """Two-tier (cheap -> expensive) theme analysis orchestration.

    Behaviour preserved from the old BlogScraper._analyze_with_models
    (see plan section 5.6): the cheap pass returns after the first
    theme that yields a parsed result; its results are discarded when
    nothing matches and the expensive pass runs over all themes,
    stopping at the first match.
    """

    def __init__(self, backend, prompt_loader, logger):
        self.backend = backend
        self.prompt_loader = prompt_loader
        self.logger = logger

    def analyse(self, content, themes,
                use_cheap_tier=True) -> dict | None:
        """Analyze content against themes.

        Returns a ``{theme_name: analysis_dict}`` mapping, or None
        when no theme produced a parsed result.
        """
        if use_cheap_tier:
            self.logger.info(
                "Starting cheap model pre-screening for %d themes",
                len(themes)
            )
            cheap_results = self._analyse_role(content, themes, 'cheap')

            if self._has_theme_match(cheap_results):
                self.logger.info(
                    "Theme match found with cheap model. "
                    "Stopping analysis to save costs."
                )
                return cheap_results

            self.logger.info(
                "No theme match with cheap models. "
                "Using expensive models for precise verification."
            )
        else:
            self.logger.info(
                "Skipping cheap tier (disabled for this URL). "
                "Using expensive models directly."
            )

        return self._analyse_role(content, themes, 'expensive')

    def _analyse_role(self, content, themes, role):
        """Run one tier over the themes.

        Themes with a missing prompt, a backend failure or unparsable
        output are skipped; the loop continues. 'cheap' returns after
        the first parsed theme (match or not); 'expensive' returns at
        the first match.
        """
        aggregated_results = {}

        for theme in themes:
            template_text = self.prompt_loader(theme.name)
            if template_text is None:
                self.logger.error(
                    "Prompt file not found for theme '%s' at %s.",
                    theme.name, theme_prompt_path(theme.name)
                )
                continue

            response = self.backend.generate(
                template_key=f'blogs.theme.{theme.name}',
                template_text=template_text,
                input_text=content,
                role=role,
            )
            if response is None:
                continue  # every model failed for this theme

            if response.blocked:
                aggregated_results[theme.name] = {
                    **response.extra,
                    theme.name: True,
                    'confidence_score': 1.0,
                    'reasoning_summary': (
                        "Content analysis blocked by API safety "
                        "filters. Reason: "
                        f"{response.block_reason}"
                    ),
                    'model': response.model_name,
                    'model_tier': role,
                    'blocked': True,
                }
                return aggregated_results

            analysis = self._parse_result(theme, response, role)
            if analysis is None:
                continue

            aggregated_results[theme.name] = analysis

            match_result = analysis.get(theme.name)
            confidence = analysis.get('confidence_score', 'N/A')
            self.logger.info(
                f"Theme '{theme.name}' analysis: "
                f"{'MATCH' if match_result else 'NO MATCH'} "
                f"(confidence: {confidence}, model: {role})"
            )

            # Stop immediately if any theme matched (content is bad,
            # no need to check other themes).
            if match_result is True:
                self.logger.info(
                    f"Stopping analysis to save costs "
                    f"(theme matched: {theme.name})"
                )
                return aggregated_results

            # Cheap tier: return after the first parsed theme, even
            # without a match.
            if role == 'cheap':
                self.logger.info(
                    "Cheap tier: Only first theme is analyzed. "
                    "Returning results after first theme."
                )
                return aggregated_results

        if not aggregated_results:
            self.logger.warning("No themes were successfully analyzed.")
            return None

        return aggregated_results

    def _parse_result(self, theme, response, role):
        """Clean, parse and shape-validate the model's JSON text.

        Returns None on any failure (missing/empty text, bad JSON or
        an invalid result shape — PR-9) — the theme is then skipped;
        parsing must never crash the run.
        """
        try:
            cleaned_json_str = (
                (response.text or '')
                .strip()
                .replace('```json', '')
                .replace('```', '')
                .strip()
            )

            # Remove trailing commas before closing braces/brackets.
            cleaned_json_str = re.sub(
                r',\s*([}\]])', r'\1', cleaned_json_str
            )

            theme_analysis = json.loads(cleaned_json_str)
        except Exception as e:
            self.logger.error(
                "Failed to decode JSON for theme '%s'. Error: %s. "
                "Response: %s",
                theme.name, str(e), (response.text or '')[:200]
            )
            return None

        if not self._valid_result_shape(theme.name, theme_analysis):
            self.logger.warning(
                "Analysis for theme '%s' failed result-shape "
                "validation (expected the theme key as a bool, "
                "'confidence_score' as a 0-1 number and "
                "'reasoning_summary' as a string) — skipping it. "
                "Response: %s",
                theme.name, (response.text or '')[:200]
            )
            return None

        theme_analysis.update(response.extra)
        theme_analysis['model'] = response.model_name
        theme_analysis['model_tier'] = role
        return theme_analysis

    @staticmethod
    def _valid_result_shape(theme_name, analysis):
        """PR-9 shape check on the parsed result.

        The theme key must be a bool, ``confidence_score`` an int or
        float in [0, 1] and ``reasoning_summary`` a str; extra keys
        (e.g. ``suitability_issue``) are allowed. The synthetic
        BLOCKED result bypasses this — it is built in
        ``_analyse_role`` and never goes through the parse path.
        """
        if not isinstance(analysis, dict):
            return False
        confidence = analysis.get('confidence_score')
        return (
            type(analysis.get(theme_name)) is bool
            and type(confidence) in (int, float)
            and 0 <= confidence <= 1
            and isinstance(analysis.get('reasoning_summary'), str)
        )

    def _has_theme_match(self, results):
        """Check if any theme matched (returned True)."""
        if not results:
            return False

        for theme_name, analysis in results.items():
            if analysis.get(theme_name) is True:
                self.logger.info(
                    f"Theme '{theme_name}' matched with "
                    f"model {analysis.get('model')}"
                )
                return True

        return False
