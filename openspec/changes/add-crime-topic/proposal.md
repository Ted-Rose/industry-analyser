# Proposal

## Why

Routine crime coverage tops the daily digest. On 2026-11-09,
11 of 20 ranked items were untopicked crime/local-news
stories (sentencing, missing persons, drunk driving) that
qualified via the `topic IS NULL AND source_count >= 2`
rule and scored with the NULL-topic effective weight of
1.0 — a 5-outlet crime story outranked every economics,
politics and war story that day. The pipeline has no `crime`
topic, so there is no lever to demote this coverage without
excluding it entirely.

## What Changes

- New `crime` seed topic (`Noziedzība`) in
  `news/topics.py`'s `TOPICS`, with a curated Latvian
  keyword list and `weight` **0.4** — deliberately the
  lowest topic weight.
- The demotion is the tagging itself: a crime story
  currently sits at effective weight 1.0 (NULL topic,
  `_refresh_story` defaults `weight` to 1.0). Tagging it
  `crime` moves it to 0.4, so a 5-outlet crime story drops
  from ~5.3 to ~2.1 — below a 2-outlet economics story
  (~2.6) — while still surfacing when coverage is broad.
- Tests asserting the seed exists with the low weight, that
  crime headlines classify as `crime`, and that a tagged
  crime story scores below an identical untopicked one.
- `docs/news_pipeline.md` updated (topic list, weights,
  plain-words section).
- Ops follow-up (maintainer machine, NOT the agent — prod
  DB is read-only for `ai_agent`): `seed_news_sources`
  creates the row on the next `scrape_news` anyway; run
  `reclassify_news_articles --all` once to retag the
  corpus, then rebuild recent digests with
  `build_news_digest --date D`.

## Capabilities

### New Capabilities
<!-- The news topic set is data (seed TOPICS tuple), not a
     spec'd capability — precedent: add-news-pipeline-command
     shipped without a spec delta. -->

### Modified Capabilities
<!-- Digest ranking behavior changes via data weights only;
     no spec'd contract changes. -->

## Impact

Backend data-layer only. Touched code: `news/topics.py`
(seed tuple + curation comments), `news/tests.py`,
`docs/news_pipeline.md`. No model changes, no migration —
`NewsTopic` rows are seeded by `ensure_seeded`
(`get_or_create`) inside `scrape_news`, so the row appears
on the next routine scrape; `seed_news_sources` does it
sooner. No API, frontend or terraform changes.
