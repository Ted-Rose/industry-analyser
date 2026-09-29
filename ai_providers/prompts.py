"""Deterministic prompt assembly (plan section 5.1).

The layout name is stored on every AIRequest, so a prompt is always
rebuilt exactly as ``render_prompt(template.text, input.text, layout)``.

Invariant: a layout's rendering never changes once merged. Any change
is a new layout name. The golden-output tests in test_providers.py pin
each layout's exact output.
"""

from ai_providers.types import RenderedPrompt


def _render_inline_v1(template_text, input_text):
    # Byte-identical to the historic blogs/scraper.py concatenation:
    # prompt_instructions + "\n\n---\n\n" + article_content
    return RenderedPrompt(user=template_text + '\n\n---\n\n' + input_text)


def _render_system_v1(template_text, input_text):
    return RenderedPrompt(
        system=template_text,
        user='<input>\n' + input_text + '\n</input>',
    )


def _render_raw(template_text, input_text):
    # Ad-hoc / smoke prompts: the input is the whole prompt.
    return RenderedPrompt(user=input_text)


PROMPT_LAYOUTS = {
    'inline_v1': _render_inline_v1,
    'system_v1': _render_system_v1,
    'raw': _render_raw,
}


def render_prompt(template_text, input_text, layout='inline_v1'):
    """Assemble a RenderedPrompt for the named immutable layout."""
    try:
        renderer = PROMPT_LAYOUTS[layout]
    except KeyError:
        known = ', '.join(sorted(PROMPT_LAYOUTS))
        raise ValueError(
            f'Unknown prompt layout {layout!r}; expected one of: {known}'
        ) from None
    return renderer(template_text, input_text)
