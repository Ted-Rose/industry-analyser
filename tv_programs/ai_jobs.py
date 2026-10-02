"""AI job specs declared by the tv_programs app."""

from ai_providers.jobs import AIJobSpec

TITLE_TRANSLATION = AIJobSpec(
    slug='tv_programs.title_translation',
    description='Translate LV TV show titles to English for IMDb lookup',
    roles=('translate',),
    default_assignments={
        'translate': [('gemini', 'gemini-2.5-flash-lite')],
    },
)
