# Property Linking Plan — dedup ads into canonical properties

## Executive Summary

**Problem**: The same physical apartment/house is listed by multiple
ss.com ads. Sellers delete and re-create ads (the portal doesn't allow
editing), agents re-post, and the same unit can even appear in both
rent and sale categories. Per-ad statistics (avg price, days on
market) are inflated and skewed.

**Measured duplication** (local DB, 2026-10-01): grouping by
`(street_name, street_no, rooms, size)` shows ~12% excess rows in
`ApartmentForRent`, ~16% in `ApartmentForSale` (up to ~20% with ±2.5m²
size tolerance), ~5–6% for `HouseForRent`, ~7–9% for `HouseForSale`.

**Solution**: New `ApartmentProperty` / `HouseProperty` tables (shared
abstract `BaseProperty`). Each ad gets a nullable `property` FK; many
ads → one property. A scoring-based matcher links ads to properties;
high-confidence matches auto-link, mid-confidence matches go to a
review queue (admin actions), low-confidence ads create a new
property. A backfill management command (`--dry-run`) links existing
data. Rent and sale ads share one property record per physical unit.

**Non-goal**: scrape-time linking — matching runs via the backfill
command only (per decision below). The command is idempotent, so it
can be run after each scrape or on a schedule.

---

## Why naive dedup doesn't work

1. **`apartment_no` is empty on ~98% of apartment ads** — ss.com
   listing rows rarely expose it. `street_name + street_no` identifies
   a *building*, not a unit. Address-only grouping produces ~38–45%
   "duplicates" which are mostly different flats in the same building.

2. **Identical physical fingerprints can still be different units.**
   Observed: `Chaka 133`, six ads with identical
   rooms/size/floor/max_floor from 3 sellers — but the comments reveal
   "Dzīvoklis Nr. 56" vs "Nr. 49": the building is being sold off
   flat-by-flat. A pure fingerprint key would merge distinct units.

3. **The same property can change hands** — ~46% of same-fingerprint
   groups span multiple `Seller` rows (owner vs agent re-posts, agent
   changes), so `seller` equality is a strong positive signal but
   cannot be required.

4. **Ad listings are editable-looking but reposted**: price, size and
   description drift slightly between reposts, so matching must be
   fuzzy (scored), not exact.

### Available matching signals

| Signal | Strength | Notes |
|---|---|---|
| `street_name` + `street_no` | required (gate) | building-level identity |
| `apartment_no` | hard reject on conflict | populated on only ~2% of ads; can also be parsed from `comment` ("Dzīvoklis Nr. 49") |
| `rooms` | hard reject on conflict | identical-layout flats share it, but a conflict is decisive |
| `size` | scored (±tolerance tiers) | sellers round/edit; ±1 m² strong, ±10% weak |
| `floor` / `max_floor` | scored | floor mismatch weakens, doesn't disqualify (mis-typed floors exist) |
| `seller` (phone / `contact_id`) | scored | same seller + same building = very likely repost |
| `comment` similarity | scored | reposts often reuse description text; also a *disambiguator* when it names a different flat number |
| temporal adjacency | scored | ad A `last_seen` ≈ ad B `first_seen` is the classic delete+repost signature |
| `land_area_sqm` (houses) | scored | strong extra signal; house dup rates are low anyway |

---

## Solution Design

### Schema

Following existing conventions (abstract bases, explicit `db_table`):

```python
class BaseProperty(models.Model):
    region = models.ForeignKey('Region', null=True, blank=True,
                               on_delete=models.SET_NULL,
                               related_name='%(class)s_properties')
    district = models.CharField(max_length=255)
    street_name = models.CharField(max_length=255)
    street_no = models.CharField(max_length=50, blank=True)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()

    class Meta:
        abstract = True


class ApartmentProperty(BaseProperty):
    apartment_no = models.CharField(max_length=50, blank=True)
    rooms = models.IntegerField()
    size = models.FloatField()
    floor = models.IntegerField()
    max_floor = models.IntegerField()
    project = models.ForeignKey('Project', null=True, blank=True,
                                on_delete=models.SET_NULL)

    class Meta:
        db_table = 'classified_ads_apartment_property'


class HouseProperty(BaseProperty):
    rooms = models.IntegerField()
    size = models.FloatField()
    floors = models.IntegerField()
    land_area_sqm = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'classified_ads_house_property'
```

Ad side — added to each concrete ad model (explicit, so
`related_name`s read naturally):

```python
# ApartmentForRent / ApartmentForSale
property = models.ForeignKey(
    ApartmentProperty, null=True, blank=True,
    on_delete=models.SET_NULL, related_name='rent_ads',  # 'sale_ads'
)
# HouseForRent / HouseForSale -> HouseProperty likewise
```

Plus link-audit fields on each ad model (put them on the abstract
bases so they apply to all four):

```python
MATCH_STATUS_CHOICES = [
    ('unmatched', 'Unmatched'),
    ('auto', 'Auto-linked'),
    ('candidate', 'Pending review'),
    ('manual', 'Manually linked'),
]
property_match_status = models.CharField(
    max_length=20, choices=MATCH_STATUS_CHOICES, default='unmatched')
property_match_score = models.FloatField(null=True, blank=True)
candidate_property = models.ForeignKey(
    ApartmentProperty, null=True, blank=True,
    on_delete=models.SET_NULL, related_name='+')
```

`candidate_property` holds the *proposed* link for review-queue rows;
`property` stays null until a human (or the auto threshold) confirms.
No separate candidate table needed — the review queue is just
`filter(property_match_status='candidate')`.

> `property` is a reserved-ish name in Python but a valid Django field;
> if preferred, name it `linked_property`. Decide at implementation.

### Matcher — `classified_ads/property_matcher.py`

```python
def match_property(ad, property_qs) -> tuple[Property|None, float, str]
```

1. **Block**: candidates = `property_qs.filter(
   street_name__iexact=norm(ad.street_name),
   street_no=norm(ad.street_no), district=ad.district)`. Normalize
   street names (lowercase, strip, collapse whitespace, unify
   "iela"/"ielas"/"ielā" suffixes) before comparing.
   No candidates → `(None, 0.0, 'new')`.

2. **Hard rejects** (candidate dropped):
   - `rooms` differ;
   - `size` differs by >15%;
   - `apartment_no` conflict — both sides have one (stored or
     comment-extracted) and they differ. This is what keeps the
     "Chaka 133" flats apart.

3. **Score** remaining candidates (weights tuned on dry-run output):

   | Signal | Points |
   |---|---|
   | same `seller` (phone or contact_id) | +0.30 |
   | `size` within ±1 m² / ±3% / ±10% | +0.25 / +0.18 / +0.08 |
   | `floor` equal | +0.15 |
   | `max_floor` equal | +0.05 |
   | `project` equal (non-null) | +0.10 |
   | `land_area_sqm` equal (houses) | +0.20 |
   | comment similarity ≥0.8 (token Jaccard or `difflib`) | +0.15 |
   | temporal adjacency (gap ≤14 days between `last_seen` and `first_seen`) | +0.10 |
   | `apartment_no` equal (non-empty) | +0.40 |

4. **Decide** on the best candidate:
   - score ≥ **0.80** → link, `match_status='auto'`;
   - 0.45–0.80 → `match_status='candidate'`,
     `candidate_property=best`;
   - < 0.45 → create a new property, `match_status='auto'`
     (self-evident singleton).

   Thresholds are command flags so dry-runs can tune them.

### Canonical property attributes

Set from the "best" ad in the cluster — most sightings, tie-break
most complete non-empty fields. On each link, extend
`first_seen`/`last_seen`. Recompute via `property.refresh_from_ads()`
helper so re-runs and manual relinks stay consistent.

### Backfill command

`classified_ads/management/commands/link_ads_to_properties.py`:

```
python manage.py link_ads_to_properties \
    [--deal rent|sale] [--type apartment|house] \
    [--dry-run] [--batch-size 500] \
    [--auto-threshold 0.8] [--candidate-threshold 0.45] \
    [--limit N]
```

- Processes unlinked ads oldest-first (`first_seen`) so the property
  cluster accumulates in chronological order — repost chains link
  correctly.
- Ads created this run's earlier iterations are eligible candidates
  (in-memory + DB), so A→B→C chains collapse onto one property.
- `--dry-run` prints per-table counts: new properties, auto-links,
  candidates, and the score histogram for threshold tuning.
- Idempotent: a second run only touches `match_status='unmatched'`
  rows. `--relink` flag (opt-in) reconsiders `auto`-linked ads too.

### Review queue (admin)

- `ApartmentPropertyAdmin` / `HousePropertyAdmin`: changelist +
  inline of linked ads (both rent and sale inlines on
  `ApartmentProperty`).
- Ad admins: `property_match_status` in `list_filter`; a filtered
  changelist view (`candidate`) is the review queue.
- Admin actions on candidate ads: **Confirm link** (sets `property=
  candidate_property`, `match_status='manual'`) and **Reject** (clears
  `candidate_property`, `match_status='manual'` + `property` left
  null so the next run can re-candidate or create a fresh property —
  or a "Create new property" action).

### Stats impact

- `days_on_market` = distinct union of `seen_on` across all linked
  ads' sightings (survives delete+repost — the metric `days_active`
  can't express).
- Price history across linked ads shows real price cuts, not
  "new listing" resets.
- Region stats views (`_compute_apartment_region_stats` etc.) can
  group by property: `Avg`/`Count` over `property` instead of per-ad
  rows, optionally restricted to `match_status__in=('auto','manual')`.

---

## Implementation Steps

### Phase 1 — Schema + admin (PR 1)

1. Add `BaseProperty`/`ApartmentProperty`/`HouseProperty`, the
   `property`/`candidate_property` FKs and match-audit fields.
2. **User runs** `makemigrations` + `migrate` (guardrail — never run
   these ourselves).
3. Register property admins with linked-ads inlines; add
   `property_match_status` filter + confirm/reject actions on the four
   ad admins. Admins must use `all_objects` (`get_queryset` override)
   per the existing convention.

### Phase 2 — Matcher + tests (PR 2)

1. `classified_ads/property_matcher.py`: normalization, blocking,
   hard rejects, scoring, threshold decision.
2. Real unit tests in `classified_ads/tests.py` (currently a stub):
   repost chain links; Chaka-133-style same-building different flats
   stay split via conflicting `apartment_no`/comment number;
   rent+sale ads of one unit share a property.

### Phase 3 — Backfill command (PR 3)

1. `link_ads_to_properties` with `--dry-run` first; tune thresholds on
   dry-run histograms; run for real.
2. Review the `candidate` queue in admin; confirm/reject.

### Phase 4 — Property-level stats (PR 4)

1. Extend region stats views to aggregate per-property; add
   `days_on_market` and price-history-per-property display.
2. Optionally add a property list/detail UI under `/classified-ads/`.

### Later (out of scope now)

- Scrape-time linking (call matcher in `create_or_update_resources`
  for new ads) — the command covers it for now.
- Comment apartment-number extraction feeding `apartment_no`
  (improves the hard-reject signal).
- Cross-category rent↔sale linking uses the same matcher over the
  shared property table — verify on real data during Phase 3.

## Rollback Plan

1. Code: `git revert`.
2. Data: links are additive — clearing `property`/
   `candidate_property`/`property_match_*` restores pre-link state;
   dropping the property tables removes everything. No destructive
   change to ads or sightings.

## Risks & Notes

- **False merges** (two real units merged): mitigated by hard rejects
  and the candidate queue; residual risk is identical-fingerprint
  flats with no distinguishing signal — acceptable at the auto
  threshold, correctable via admin unlink.
- **False splits** (one unit → two properties): less harmful to
  stats than false merges; manual "merge properties" admin action can
  be added if it proves common.
- **Threshold tuning is empirical** — the first `--dry-run` histogram
  decides whether 0.80/0.45 are right.
- **`street_name` normalization** needs care: source mixes
  "Čaka"/"A. Čaka iela", korpus suffixes ("54 k-3"), and the known
  address-parsing bugs (`docs/address_parsing_fix_plan.md`) — ~5% of
  apartment rows have misparsed street/street_no/apartment_no and will
  match poorly until refetched.

## Success Criteria

- `link_ads_to_properties --dry-run` shows excess-row reduction close
  to the measured 12–20% (apartments) / 5–9% (houses) at the chosen
  thresholds, with a small candidate residue.
- Spot-check: known repost groups (e.g. a `Chaka 133` cluster) — same
  unit merges, different flat numbers stay separate.
- Region stats computed per-property differ measurably from per-ad
  stats (lower listing counts, longer days-on-market).
- Re-running the command after the next scrape links only new ads.
