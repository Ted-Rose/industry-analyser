"""Pure-Python topic classifier — keyword hit counts over
title + lead (precedent: fetcher/scraper.py's
_find_keywords_in_content). No paid AI calls."""
import logging
import re

logger = logging.getLogger('news')


def classify_topic(title, lead, topics):
    """Return the enabled NewsTopic with the most keyword hits in
    ``title + lead``, or None when nothing matches.

    ``topics`` is an iterable of objects with ``keywords`` (list
    of strings) and ``is_enabled``. Pure function — easy to test.
    """
    text = f"{(title or '').lower()} {(lead or '').lower()}"
    best_topic = None
    best_hits = 0
    for topic in topics:
        if not getattr(topic, 'is_enabled', True):
            continue
        hits = 0
        for keyword in topic.keywords or []:
            pattern = r'\b' + re.escape(keyword.lower()) + r'\b'
            if re.search(pattern, text):
                hits += 1
        if hits > best_hits:
            best_topic = topic
            best_hits = hits
    return best_topic
