# Tasks

## 1. Seed topic

- [x] 1.1 backend: Append the `crime` topic dict to `TOPICS`
  in `news/topics.py` — LAST in the tuple (tie-break: crime
  loses ties to higher-weighted topics, see design.md §3) —
  using the exact `slug`/`name`/`weight`/`keywords` block
  from design.md §4, with the curation comments inlined per
  the file's existing style (the comment block at the top
  of the file explains '='/'*'/stem forms; add a short
  note on why `'tiesas*'`/`'=tiesa'`/`'=soda'` forms were
  chosen and why `'korupc*'`/`'ieroc*'`/`'šāv*'` are
  deliberately absent). Keep every line ≤ 79 chars.
  Verify: `python manage.py check` passes;
  `python manage.py seed_news_sources --dry-run` lists the
  topic as would-be-created (do NOT run the real seed —
  prod DB).

## 2. Tests

- [x] 2.1 backend: In `news/tests.py` (follow the existing
  classification/clustering test style — search for
  `classify_topic` tests and mirror): (a) a crime headline
  like "Vīrietim par slepkavību piespriests cietumsods"
  classifies as `crime`; (b) a politics headline
  ("Saeima skata likumprojektu") still classifies
  `politics`, not `crime`; (c) the seed's weight is the
  lowest in `TOPICS` (assert `0 < weight <= 0.5`); (d)
  `_refresh_story` scores a `crime` story below an
  otherwise identical untopicked story — proves the
  demotion mechanism (create a story + confirmed member,
  refresh with `topic=crime` vs `topic=None`, compare
  `importance_score`). Verify:
  `DATABASE_URL=sqlite:///db.sqlite3 python manage.py test
  news` passes.

## 3. Docs

- [x] 3.1 backend: Update `docs/news_pipeline.md`: the
  "In plain words" step 2 says "five topics" — now six
  (add `crime`); the seed-topics list in Stage 2 adds
  `crime` (0.4); the relevance-scoring weights list adds
  `crime 0.4`. Verify: documented values match
  `news/topics.py`.

## Manual ops (post-merge, maintainer machine — NOT the agent)

- `python manage.py seed_news_sources` (or wait for the
  next scheduled `scrape_news`, which seeds via
  `ensure_seeded`).
- `python manage.py reclassify_news_articles --all` —
  retags the corpus and recomputes touched stories'
  topic + `importance_score`.
- `python manage.py build_news_digest --date D` for each
  recent day worth republishing — the next daily
  `news_pipeline` covers new days automatically.
- Archive the change after merge (`openspec archive`).
