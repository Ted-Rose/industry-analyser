"""AI job specs declared by the fetcher app (plan section 5.5)."""

from ai_providers.jobs import AIJobSpec

VACANCY_IMAGE_OCR = AIJobSpec(
    slug='fetcher.vacancy_image_ocr',
    description='cv.lv vacancy image/PDF transcription to text',
    roles=('ocr',),
    default_assignments={
        'ocr': [('gemini', 'gemini-2.5-flash-lite')],
    },
)
