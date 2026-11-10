# Design

## Context

`docs/news_pipeline.md` documents the pipeline. Relevant
machinery:

- `classify_topic(title, lead, topics)` scores each enabled
  `NewsTopic`'s keyword specs over title+lead 4-char stems;
  score ≥ `MIN_TOPIC_SCORE` (2) wins, ties resolve to the
  first topic in pk order. `topic=None` otherwise.
- `_refresh_story` sets `importance_score = source_count ×
  (topic.weight or 1.0) × mean(source.importance_weight)` —
  a NULL topic scores with effective weight **1.0**.
- `ranked_stories_for(date)` admits stories with an enabled
  topic OR `topic IS NULL AND source_count >= 2`.

Today a 5-outlet crime story scores ~5×1.0×1.05 ≈ 5.25 and
tops the digest (2026-11-09 evidence). The only levers are
admin-editable weights; no `crime` topic exists to tag.

## Goals / Non-Goals

**Goals:**
- A `crime` topic catches crime/court/police coverage.
- Crime stories rank far below topicked news of equal
  coverage — "a lot less significant", not "hidden": a
  major story covered by 4+ outlets still appears.
- Zero code-path changes — data-only (seed tuple + weight).

**Non-Goals:**
- No new exclusion rules in `build_digest` /
  `ranked_stories_for` (e.g. per-topic caps) — weight alone
  achieves the demotion; a special case adds machinery for
  a policy the admin can already tune on the `NewsTopic`
  row.
- No retagging of the existing corpus in this change —
  `reclassify_news_articles --all` is a maintainer-machine
  ops step (prod is read-only for the `ai_agent` user).

## Decisions

### 1. Demote by tagging, not by digest exclusion

Tagging a crime article `crime` at weight 0.4 *lowers* its
story's score relative to leaving it NULL (effective 1.0):
`5 × 0.4 × 1.05 ≈ 2.1` vs `5 × 1.0 × 1.05 ≈ 5.25`. The
counter-intuitive bit worth documenting in code: adding the
topic is what demotes the stories — excluding crime from
the digest would also have required code, while a low
weight uses machinery that already exists.

Single-source consequence: NULL-topic singletons are
digest-ineligible today, but a `crime`-tagged singleton is
eligible at ~0.4–0.5 — it only surfaces when fewer than 20
better stories exist, which is the desired "rare, tail"
behavior.

### 2. Weight 0.4

Below `war` 1.1 and even `politics`/`diplomacy` 1.0 by a
wide margin; roughly the `jauns` source-weight precedent
(0.5, tabloid) one step lower. A 2-outlet crime story
(~0.9) sits at the tail; only 4+ outlets pushes it into
the visible range. Admin-tunable on the `NewsTopic` row —
the seed value is a default, not a policy lock.

### 3. `crime` goes LAST in `TOPICS`

Score ties resolve to the first topic in pk order
(classification callers `order_by('pk')`; seeds are created
in tuple order). Last position means crime loses ties —
deliberate: an article equally matching crime and politics
keeps the higher-weighted politics tag, so the low weight
can't accidentally capture ambiguous hard news.

### 4. Keyword list — curated against greedy 4-char stems

Same curation rules as existing seeds (see the comment
block atop `news/topics.py`): `'='` exact / `'*'` prefix /
plain stem; multi-word keywords need ALL word-specs.

```python
{
    'slug': 'crime',
    'name': 'Noziedzība',
    'weight': 0.4,
    'keywords': [
        'nozieg*', 'noziedz*', 'slepkav*', 'nogalin*',
        'zādz*', 'zagl*', 'zagt*',
        'cietum*', 'ieslodz*', 'noties*', 'piesprie*',
        '=soda', '=sods', '=sodu',
        'policij*', 'prokur*', 'kriminā*',
        'tiesas*', 'tiesneš*', '=tiesa', 'prāv*',
        'aiztur*', 'apcietin*', 'aizdom*',
        'krāpniec*', 'krāpš*', 'blēdīb*',
        'izvaro*', 'vardarb*', 'narkot*',
        'nolaup*', 'teror*', 'šantāž*',
        'dzērāj*', 'muit*', 'kontraband*',
        'cilvēku tirdzniecīb*', 'Valsts robežsardz*',
    ],
}
```

Notes the implementer must encode as comments (the file's
convention — every non-obvious choice is explained inline):

- `'cietum*'` covers `cietumsods`/`cietumā`/`cietumnieks`;
  `'cietis'` (suffered) stems `cieti` — safe.
- `'tiesas*'` (court's/of court) and `'=tiesa'` avoid the
  `'ties*'` stem that would hit `tiesības`/`tiesu`/`tieši`.
- `'=soda'/'=sods'/'=sodu'` exact — `'soda'` the drink is
  an accepted rare false positive (precedent: `banka*`
  also hits jars).
- `'zagt*'` + `'zagl*'` cover `zagt`/`zagta`/`zaglis`;
  `'zādz*'` covers `zādzība` — different roots.
- `'cilvēku tirdzniecīb*'` — `cilv` stem + `tirdzniecīb*`
  prefix; both required, so generic trade talk without a
  `cilvēk*` token cannot hit.
- `'Valsts robežsardz*'` — border-guard smuggling/
  crossing cases; requires both the `valsts` stem and the
  `robežsardz*` prefix.

Deliberately EXCLUDED (document why in a comment):

- `'korupc*'`/`'korump*'`/`'=KNAB'` — corruption coverage
  is usually politically significant (officials,
  institutions); demoting it to 0.4 would bury exactly the
  accountability stories the digest exists to rank high.
  They keep hitting `politics`/`economics` keywords.
- `'ieroc*'` — weapons keywords would drag Ukraine arms-
  supply stories out of `war`'s keyword set into a 0.4
  topic.
- `'šāv*'`/`'nošāv*'` — `šāvējs` is a sport shooter; the
  sports pages would tag `crime`.
- `'pārkāpum*'` — too broad (sanctions/rules violations).
- `'miruš*'`/`'miris'` — obituaries and accidents are not
  crime.

### 5. Seeding and backfill of existing rows

`ensure_seeded` (`get_or_create` only) creates the
`NewsTopic` row on the next `scrape_news` run — no code
path needed. New articles tag at ingest via
`initiate_resource`. Existing rows keep NULL/old topics
until the maintainer runs
`reclassify_news_articles --all` on their machine (it also
recomputes each touched story's topic and
`importance_score` via `_refresh_story`), then rebuilds
recent digests (`build_news_digest --date D`). Documented
as an ops step — never run by the agent (prod `ai_agent`
is read-only).
