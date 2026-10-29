"""Shared detection of rental ads that are actually for-sale listings.

ss.com hosts "sell or rent" dual listings: the same ad (one stable
``tr_`` id) is posted in both the ``hand_over/`` and ``sell/``
sections, and its single displayed price lands in the rent table as
``monthly_price``. Two complementary signals flag such rows:

1. Cross-deal twin: the same ``ad_id`` exists in the sale table.
   Checked by the scrapers/backfill commands against
   ``*ForSale.all_objects`` — kept out of this module because the
   rent-vs-sale model pairing differs per ad type.
2. Heuristic below: sale-scale price or Latvian/Russian sale
   vocabulary in the comment.

See: docs/misclassified_sale_ads_analysis.md
"""

PRICE_THRESHOLD = 50
SALE_KEYWORDS = [
    'pārdod', 'pārdošan', 'pārdots', 'izpirkum', 'pirkt',
    'pardod', 'pardosan', 'pardots',
    'продаётся', 'Продаем', 'Продается', 'Продам',
]


def is_sale_misclassified(comment, monthly_price_per_sqm):
    """
    Check if a rental ad is actually a for-sale listing (Strategy C+).

    Two complementary signals:
    1. Price signal: monthly_price_per_sqm > 50 (sale price entered
       as rent)
    2. Keyword signal: Latvian/Russian sale vocabulary in comment

    See: docs/misclassified_sale_ads_analysis.md
    """
    if monthly_price_per_sqm > PRICE_THRESHOLD:
        return True

    comment_lower = (comment or '').lower()
    for keyword in SALE_KEYWORDS:
        if keyword.lower() in comment_lower:
            return True

    return False
