# Duplicate ad rows quarantine (same link, different ad_id)

One-time data fix applied 2026-10-05 against the production Aiven DB.
Script: `scripts/hide_duplicate_link_ads.py` (`--dry-run` to inspect,
no flag to apply).

## Root cause

Before commit `b833b94` ("Use stable ss.com tr_ id as classified ad
ad_id") the scrapers built `ad_id` as the ss.com `tr_<n>` row id plus
concatenated listing-cell text. The `tr_`-prefix dedupe
(`scripts/dedupe_classified_ads.py`, see
`docs/ad_id_dedup_fix_plan.md`)
merged most of the fallout, but a residue remained: rows in the same
table sharing the **exact same `link`** under different `ad_id`s —
literal duplicate rows of one listing. Typical shapes:

- real id + appended cell text:
  `tr_54290794Skolas 23606/6Spec. pr.`, `tr_57749364Lives 7a8011200 m²`
- real id + appended digits: `tr_5788233925`, `tr_565885772`
- two well-formed-looking ids where one is real + extra digit(s)

## Method

For each of the four ad tables, group `all_objects` rows by `link`
where count > 1. Keep exactly one canonical row visible per group;
set `is_hidden=True` on the rest.

Canonical-pick rule (applied in order):

1. **Visible rows only.** If the group has both hidden and visible
   rows, the canonical row is chosen among the visible ones — nothing
   already hidden is un-hidden just to change which row is canonical.
   A hidden row is picked as canonical only when ALL rows in the
   group are hidden (none occurred).
2. **Real ad_id preferred**: `ad_id ~ ^tr_\d{7,9}$` beats malformed
   ids within that pool.
3. **Most sightings**, then **earliest first_seen**, then pk.

Rows already `is_hidden=True` were not rewritten. `last_seen` was
preserved on hidden rows (`update(is_hidden=True,
last_seen=F('last_seen'))`), so `is_hidden` is the only field that
changed.

## Results

| Table | Groups | Rows in groups | Surplus | Newly hidden | Already hidden | Split-property groups |
|---|---|---|---|---|---|---|
| `classified_ads_apartment_rent` | 83 | 168 | 85 | 79 | 6 | 72 |
| `classified_ads_apartment_sale` | 123 | 248 | 125 | 106 | 19 | 103 |
| `classified_ads_house_rent` | 16 | 32 | 16 | 12 | 4 | 3 |
| `classified_ads_house_sale` | 82 | 164 | 82 | 40 | 42 | 1 |
| **Total** | **304** | **612** | **308** | **237** | **71** | **179** |

`is_hidden` counts before → after:

- `apartment_rent`: 4,357 → 4,436 (+79)
- `apartment_sale`: 5,436 → 5,542 (+106)
- `house_rent`: 1,070 → 1,082 (+12)
- `house_sale`: 3,159 → 3,199 (+40)

All 237 newly hidden rows are property-linked (`property_id` set).

**Important**: hiding an ad row does NOT merge its property row.
179 groups point at more than one `property_id` — i.e. the same
listing produced two property rows. That property-level dedup is a
separate, tracked issue; see `docs/property_match_review_2026_10.md`.

## Anomalies / nuances

- **0 all-hidden groups** — every group had at least one visible row,
  so no hidden row was promoted to canonical.
- **0 truly ambiguous picks** (no two rows in a final pool tied on
  both sightings and first_seen).
- **25 groups had two visible rows that both match `^tr_\d{7,9}$`**
  (8 in rent, 13 in sale apartments, 4 in house_sale) — e.g.
  `tr_565885772` vs `tr_56588577`. One is almost certainly the real id
  plus an appended digit, but there is no way to tell which from the
  data alone, so most-sightings/earliest-first_seen decided.
- **36 groups had no well-formed ad_id among visible rows** (1
  apartment_sale, 4 house_rent, 31 house_sale). Most are cases where
  the real-id row was already hidden and only a composite-id row
  remains visible, e.g. keep `tr_57749364Lives 7a8011200 m²` while
  `tr_57749364` stays hidden. These visible composite-id rows are
  effectively frozen — future scrapes key on the bare `tr_` id, which
  resolves to the hidden row — but un-hiding was out of scope for
  this fix.

## How to verify

Per table, each dup-link group must have exactly one visible row:

```python
from collections import defaultdict
from django.db.models import Count

dup_links = (M.all_objects.values('link').annotate(n=Count('id'))
             .filter(n__gt=1).values_list('link', flat=True))
groups = defaultdict(list)
for ad in M.all_objects.filter(link__in=dup_links):
    groups[ad.link].append(ad)
bad = [l for l, r in groups.items()
       if sum(1 for a in r if not a.is_hidden) != 1]
# bad == []
```

Post-write result: 0 non-conforming groups in all four tables.

**Recurrence**: none expected — verification on 2026-10-06 shows all
294 malformed `ad_id`s were created in a single 2026-09-29
13:40–13:44 batch (a one-off re-import, not the live scraper; current
code stores bare `tr_` ids). This quarantine is a completed one-time
fix, not an ongoing cleanup.

To undo a specific group, flip `is_hidden` back on the hidden rows
via `all_objects` (the `objects` manager filters them out).
