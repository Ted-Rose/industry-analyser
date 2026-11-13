# Plan: news digest relevance fixes

> **Status**: Implemented. Defect 1: `_refresh_story` re-derives
> `story.topic` as the modal confirmed-member topic on every
> refresh; `reclassify` runs inside `news_pipeline` between
> `link_news_stories` and `build_news_digest`. Defect 2:
> `MIN_TOPIC_SCORE = 2` gate, `finansējum*`/`raķet*` keywords.
> Defect 3: digest admits NULL-topic stories with
> `source_count >= 2`.


Context: investigation of the `news` pipeline (keyword topic
classification + Jaccard story clustering + weighted
importance digest) found three defects that measurably hurt
digest quality on prod. This plan fixes them. No model
changes — no migration required.

## Defect 1 — `NewsStory.topic` is frozen at creation

`news/clustering.py::_refresh_story` sets `story.topic` only
in the story-creation branch (first member article) and never
re-derives it as members accrue. Meanwhile `scraper.py` can
retag article topics on re-seen RSS items, so 64 prod stories
have `topic=NULL` while containing topic-tagged confirmed
members — including the two highest-coverage stories in the
DB (source_count 7 and 6), which were wrongly excluded from
the digest.

Fix:

- In `_refresh_story` (news/clustering.py), after recomputing
  `source_count`/`importance_score`, re-derive `story.topic`
  as the modal `topic` among the story's *confirmed* member
  articles (`story_match_status in ('auto','manual')`),
  ignoring NULL member topics; tie-break by lowest topic pk
  for determinism. NULL only if every confirmed member is
  NULL. This must run unconditionally on every refresh, not
  just at creation — remove the create-time-only assignment
  so there is a single code path.
- Add `reclassify_news_articles` to the daily sequence in
  `scrape_jobs/management/commands/run_all_jobs.py`
  (immediately after `link_news_stories`, before
  `build_news_digest`) so already-linked stale stories also
  get re-derived.

## Defect 2 — keyword false positives/misses

`news/topics.py` + `news/classification.py`:

- `war`: add `'raķet*'` — `'raķeš*'` misses the nominative
  "raķete"/"raķetes" (36 prod NULL articles affected).
- `government-funding`: change `'finansējums'` to
  `'finansējum*'`. Bare `'finansējums'` 4-char-stems to
  `'fina'`, matching every "finanšu X" phrase (sanctions,
  parenting features, corporate trouble) — the source of
  multiple misclassified digest items. `'finansējum*'`
  still catches all declensions of the actual word.
- `classification.py::classify_topic`: add a minimum-score
  gate — an article must reach `MIN_TOPIC_SCORE = 2` (a
  single title hit, or two lead hits) to get a topic; below
  that it stays NULL. Module-level constant, used in the
  winner selection. Update the docstring.

Note: keyword edits only affect newly classified articles.
The PR body must tell the maintainer to run
`python manage.py seed_news_sources --sync` and
`python manage.py reclassify_news_articles --all` against
prod after merge to retag the backlog (manual step, matches
the repo's no-CI-migration convention).

## Defect 3 — digest excludes top stories with `topic=NULL`

`news/digest.py::build_digest` filters
`topic__is_enabled=True`, categorically dropping NULL-topic
stories regardless of coverage. A 7-outlet story lost to a
1-outlet keyword match.

Fix: eligibility becomes

    (topic is enabled) OR (topic IS NULL AND source_count >= 2)

Single-source untopicked stories stay excluded (sports/
celebrity singletons would otherwise flood the digest); a
multi-outlet cluster is itself strong importance evidence.
Implement via `Q` objects in the existing queryset;
keep the `articles__story_match_status__in=CONFIRMED`
condition unchanged.

## Tests (update/add under news/tests/)

- Story topic re-derived from confirmed members when members
  accrue; NULL only when all confirmed members are NULL;
  candidate members do not vote.
- `classify_topic` below-threshold → None; title-hit alone
  still classifies.
- `'raķete'` headline classifies as war; a generic "finanšu
  prasmes" headline does NOT classify as government-funding.
- Digest includes a `source_count>=2` NULL-topic story and
  still excludes a `source_count=1` NULL-topic story.
- run_all_jobs ordering: reclassify runs between link and
  digest (assert command list order if the test harness
  allows; otherwise at least that reclassify is invoked).

## Verify

    python manage.py check
    DATABASE_URL=sqlite:///db.sqlite3 python manage.py test news

## Out of scope (deliberate)

Moving `scrape_news` off the `local:daily` gate to Cloud Run
(Latvian sites may block GCP egress IPs — maintainer decision),
candidate-review UI, story merging, `jauns` weight rebalance.
