"""Pure-Python topic classifier — keyword hit counts over
title + lead (precedent: fetcher/scraper.py's
_find_keywords_in_content). No paid AI calls.

Each whitespace-separated word of a keyword carries an
optional match-type marker:

  '=word'  EXACT  — the literal token must appear, unstemmed
                    ('=Latvenergo' hits 'Latvenergo' but not
                    'Latvijas')
  'word*'  PREFIX — a token starting with 'word' must appear
                    ('premjer*' hits 'premjerministrs' and
                    'premjeru' but not 'premija')
  'word'   STEM   — the word's 4-char stem must appear (the
                    same stemmer news.clustering uses for
                    story clustering: 'Saeimas' hits 'Saeima',
                    'valdības' hits 'valdība')

The markers exist because 4-char stems are too greedy for
short roots: 'Latvenergo' stems to 'latv' and would hit every
Latvijas/latviešu token; 'līdzfinansējums' stems to 'līdz' —
the preposition 'līdz' itself, which IS present in article
stems because classification runs text_stems with
drop_stopwords=False. That flag is a deliberate coupling:
stopword stems are what let 'ES fondi' match 'es', but the
same flag is why a stem keyword on a stopword-prefix root
('līdz...') would fire on the preposition — so seed keywords
on greedy roots must be curated into '=' or '*' forms rather
than left to the stemmer.

A keyword hits when ALL its word-specs match — multi-word
keywords ('ES fondi', 'atbalsta programma') need every
constituent word, order-independent. Hits fully inside the
title count double.
"""
import logging
import unicodedata

from .clustering import STEM_LEN, text_stems, text_words

logger = logging.getLogger('news')


def _parse_keyword(keyword):
    """Split a keyword into (kind, value) word-specs.

    kind is 'exact' ('=word'), 'prefix' ('word*') or 'stem'
    (plain word, value = its 4-char stem). Words are NFKC-
    lowercased to match the article-side normalization. Pure
    digit stems are skipped exactly like text_stems skips
    them, so a keyword reduced to nothing returns []."""
    specs = []
    for word in (keyword or '').split():
        word = unicodedata.normalize('NFKC', word).lower()
        if word.startswith('=') and len(word) > 1:
            specs.append(('exact', word[1:]))
        elif word.endswith('*') and len(word) > 1:
            specs.append(('prefix', word[:-1]))
        else:
            stem = word[:STEM_LEN]
            if stem and not stem.isdigit():
                specs.append(('stem', stem))
    return specs


def _spec_hits(specs, words, stems):
    """True when every word-spec of one keyword is satisfied by
    the token set ``words`` / stem set ``stems``."""
    for kind, value in specs:
        if kind == 'exact':
            if value not in words:
                return False
        elif kind == 'prefix':
            if not any(w.startswith(value) for w in words):
                return False
        elif value not in stems:
            return False
    return True


def classify_topic(title, lead, topics):
    """Return the enabled NewsTopic with the most keyword hits
    in ``title + lead``, or None when nothing matches.

    ``topics`` is an iterable of objects with ``keywords``
    (list of strings) and ``is_enabled``. Score ties resolve
    to the FIRST topic in iteration order — callers pass
    topics ordered by pk (the scraper and the reclassify
    command both .order_by('pk')) so the tie-break is
    deterministic rather than query-plan dependent.

    Keyword word-specs are compiled once per call —
    classify_topic runs once per article, so parsing and
    stemming the keyword lists is hoisted out of the
    per-article/per-topic inner loop. Pure function — easy to
    test.
    """
    title_words = set(text_words(title, drop_stopwords=False))
    words = title_words | set(
        text_words(lead, drop_stopwords=False)
    )
    title_stems = text_stems(title, drop_stopwords=False)
    all_stems = title_stems | text_stems(
        lead, drop_stopwords=False,
    )
    compiled = [
        (
            topic,
            [
                spec for spec in (
                    _parse_keyword(k) for k in topic.keywords or []
                ) if spec
            ],
        )
        for topic in topics
        if getattr(topic, 'is_enabled', True)
    ]
    best_topic = None
    best_score = 0
    for topic, specs in compiled:
        score = 0
        for spec in specs:
            if not _spec_hits(spec, words, all_stems):
                continue
            score += 1
            if _spec_hits(spec, title_words, title_stems):
                score += 1
        if score > best_score:
            best_topic = topic
            best_score = score
    return best_topic
