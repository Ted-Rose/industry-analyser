"""Pure-Python topic classifier — stem-aware keyword hit counts
over title + lead (precedent: fetcher/scraper.py's
_find_keywords_in_content). No paid AI calls.

Tokens are matched as 4-char stems (the same stemmer
news.clustering uses for story clustering), so Latvian
inflection collapses onto the keyword: "Saeimas" hits 'Saeima',
"valdības" hits 'valdība', "budžeta" hits 'budžets'.
"""
import logging

from .clustering import text_stems

logger = logging.getLogger('news')


def classify_topic(title, lead, topics):
    """Return the enabled NewsTopic with the most keyword hits in
    ``title + lead``, or None when nothing matches.

    A keyword hits when all of its stems are present in the
    text's stem set — single-word keywords need their one stem,
    multi-word keywords ("ES fondi", "atbalsta programma") need
    every constituent stem, order-independent. Hits fully inside
    the title count double. ``topics`` is an iterable of objects
    with ``keywords`` (list of strings) and ``is_enabled``.
    Pure function — easy to test.
    """
    title_stems = text_stems(title, drop_stopwords=False)
    all_stems = title_stems | text_stems(
        lead, drop_stopwords=False,
    )
    best_topic = None
    best_score = 0
    for topic in topics:
        if not getattr(topic, 'is_enabled', True):
            continue
        score = 0
        for keyword in topic.keywords or []:
            kw_stems = text_stems(keyword, drop_stopwords=False)
            if not kw_stems or not kw_stems <= all_stems:
                continue
            score += 1
            if kw_stems <= title_stems:
                score += 1
        if score > best_score:
            best_topic = topic
            best_score = score
    return best_topic
