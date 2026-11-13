# Spec Delta

## Purpose

The seeded `NewsTopic` catalog controls both what the
keyword classifier tags and how `topic.weight` multiplies
story `importance_score`. A low-weight topic is a demotion
tool: tagging an article moves its story from the
NULL-topic effective weight of 1.0 down to the topic's
weight.

## ADDED Requirements

### Requirement: Crime topic seed

The `TOPICS` seed tuple SHALL include a `crime` topic
(`Noziedzība`) whose `weight` is the lowest of any seeded
topic (≤ 0.5), so crime/court/police stories rank far below
equally-covered stories in the editorial topics while still
surfacing when coverage is broad. The topic SHALL be placed
last in `TOPICS` so pk-order tie-breaks resolve to the
higher-weighted topic.

#### Scenario: Crime story demoted below equal coverage

- **WHEN** a story about a court verdict is covered by the
  same number of outlets as an economics story
- **THEN** the crime-tagged story's `importance_score` is
  strictly lower than the economics story's, and lower than
  the same crime story would score untopicked

#### Scenario: Broad crime coverage still eligible

- **WHEN** a crime story is covered by multiple outlets
- **THEN** it remains digest-eligible (enabled topic + at
  least one confirmed member) — it ranks low, it is not
  excluded

### Requirement: Seed curation against greedy stems

`crime` keywords SHALL follow the `'='`-exact / `'*'`-prefix
/ plain-stem spec forms and SHALL NOT introduce word-specs
that collide with established false-positive roots —
notably no `'ties*'` stem (hits `tiesības`/`tieši`), no
`'korupc*'`/`'korump*'` (political corruption stays in
higher-weighted topics), no `'ieroc*'` (Ukraine arms
coverage stays in `war`) and no `'šāv*'` (sport shooters).

#### Scenario: Sport shooter headline is not crime

- **WHEN** an article title mentions `šāvējs` in a sports
  context
- **THEN** `classify_topic` does not tag it `crime`
