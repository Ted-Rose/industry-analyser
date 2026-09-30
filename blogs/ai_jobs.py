"""AI job specs declared by the blogs app (plan section 5.5).

The role names ``cheap``/``expensive`` are part of the data contract:
they land on ``PageAnalysis.model_tier``, which
``PageManager.kid_friendly()`` filters on.
"""

from ai_providers.jobs import AIJobSpec

THEME_ANALYSIS = AIJobSpec(
    slug='blogs.theme_analysis',
    description='spoki.lv page theme classification',
    roles=('cheap', 'expensive'),
    default_assignments={
        'cheap': [('gemini', 'gemini-2.5-flash-lite')],
        'expensive': [('gemini', 'gemini-2.5-pro')],
    },
)
