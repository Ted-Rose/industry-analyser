"""Built-in AIProvider presets (plan section 5.5).

``ensure_job()`` and the ``seed_ai_config`` command use these to
create missing provider rows. Presets only *seed* the database — once
a row exists it is the source of truth and edits made in admin are
never overwritten.
"""

PROVIDER_PRESETS = {
    'gemini': dict(
        display_name='Google Gemini',
        provider_type='gemini',
        api_key_setting='GEMINI_API_KEY',
    ),
    'openrouter': dict(
        display_name='OpenRouter',
        provider_type='openai_compatible',
        base_url='https://openrouter.ai/api/v1',
        api_key_setting='OPENROUTER_API_KEY',
        extra_headers={'X-Title': 'industry-analyser'},
        min_request_interval_seconds=3,
    ),
}
