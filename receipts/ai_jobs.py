"""AI job specs declared by the receipts app (plan section 6)."""

from ai_providers.jobs import AIJobSpec

RECEIPT_EXTRACT = AIJobSpec(
    slug='receipts.receipt_extract',
    description='Rimi receipt/invoice PDF → structured JSON items',
    roles=('extract',),
    default_assignments={
        'extract': [('gemini', 'gemini-3.5-flash-lite')],
    },
)
