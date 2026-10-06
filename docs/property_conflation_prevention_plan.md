# Property Conflation Prevention Plan

Follow-up to `docs/property_linking_plan.md` and the duplicate review
documented in `docs/property_match_review_2026_10.md` /
`/tmp/property_match_review_report.md`. Verified against the
production database (read-only) on 2026-10.

## Executive Summary

**Problem**: four `ApartmentProperty` rows each absorbed ads for
*multiple different units* in one settlement — the matcher merged
distinct flats because no discriminating signal ever reached it.
Three were found by the manual audit (13910, 16071, 16072); a fourth
(16037) was discovered while quantifying this plan.

**Verified root cause**: parent-region ("X un rajons") sale listings
on ss.com show only the *settlement name* in the address cell — no
street, no house number, no apartment number. Ads scraped there get
`street_no=''` and `apartment_no=''`, so every same-town apartment
lands in one blocking bucket. When one seller then posts a batch of
same-layout units (identical rooms/size/floor, boilerplate comment),
every hard reject passes and seller+size+floor+project+comment+
temporal scores sail past the 0.8 auto-link threshold.

**Live risk**: this is not a legacy artifact — the mechanism is in
the current matcher, and cross-deal split pairs are still forming
(48 apartment + 1 house in the 7 days to 2026-10-06). Every link run
without the twin shortcut can create both new conflations and new
split pairs.

**Decisive fix**: every conflated ad had a cross-deal twin (the same
`ad_id` scraped in the rent section with a full address) already
linked to the correct single-unit property. The matcher never checks
this. A "twin shortcut" — same `ad_id` in the sibling deal table →
link to the twin's property — both prevents future conflation and
repairs the 650 split-twin pairs in one pass.

**Supporting fixes**: conflation alarms that demote auto-link to
candidate, a degenerate-block guard, better `extract_apartment_no`
recall, an audit command, and a split/relink workflow.

---

## 1. Verified mechanism

### The four conflated properties

| Prop | Block (district / street / no) | Contents | Correct props (ad_id twins) |
|---|---|---|---|
| 13910 | `Tukums un rajons` / `Smārdes pag.` / `''` | 4 sale ads, 1rm 40–47m², fl 1–3/3 | 1550 (apt 11), 1551 (apt 3), 1552 (apt 8), 1553 (apt 7) |
| 16071 | `Valka un rajons` / `Seda` / `''` | 4 sale ads, 3rm 71m², fl 1–2/2 | 5681 (Saules 9 apt 1), 5685 (Miera 3 apt 12), 5686 (Miera 3 apt 4), 5687 (Miera 3 apt 1) |
| 16072 | `Valka un rajons` / `Seda` / `''` | 2 sale ads, 2rm 62–63m², fl 2/2 | 5682 (apt 6), 5683 (apt 4) |
| 16037 | `Tukums un rajons` / `Jaunpils pag.` / `''` | 2 sale ads, 2rm 48m², fl 2/2 | 5615 (`1 1`), 7795 (Saulrieti 6) |

Every conflated row: `street_no=''`, `apartment_no=''`, district is a
parent "un rajons" region, street_name is the settlement name. The
correct props live under the *town-level* region (e.g. district
`Seda`, street `Miera 3`, apt set) — **a different block key**, so the
sale ads were never even scored against them.

### Why each guard failed

1. **`apartment_no` is missing where it matters most.** Stored
   coverage: 189/12,118 sale ads (1.6%), 234/11,671 rent (2.0%);
   `extract_apartment_no(comment)` adds only 98 hits across 23,812
   non-empty comments (0.4%). On all ten conflated ads both sources
   are empty, so `ad_no` is `''` and the apt_no hard reject
   (`_hard_reject`, `property_matcher.py:131`) can never fire.

2. **The other rejects don't apply.** Rooms are identical within
   each cluster; sizes pass the 15% gate by luck (40 vs 47 m² is
   14.9%); floor mismatch is only a missed +0.15, never a reject.

3. **Additive scoring then does the damage.** Reconstructed scores:
   seller +0.30, size ≤1m² +0.25, floor +0.15, max_floor +0.05,
   project +0.10, comment Jaccard +0.15 (the "comments" are the
   agency's boilerplate — identical across different units),
   temporal +0.10 → 0.80–1.10. E.g. on 16071: tr_57743400 created
   the property (score 0.33 → 'new'), then tr_57743380 0.80,
   tr_57743365 0.95, tr_57743358 1.10 all auto-linked within one
   run — all four ads first_seen the same day (batch posting).

4. **The review queue approved one anyway.** tr_56869274 on 13910 is
   `manual`/0.75 — it went through the candidate band and a human
   confirmed it, because the admin shows no "this property already
   contains other units" signal.

5. **Latent weakening** (as predicted): `_property_apartment_nos`
   unions every linked ad's number, so a property that already holds
   two flats' numbers would accept a third — self-reinforcing.

### Where the data loss happens (scraper)

`parse_results` *does* extract an apartment number — `_split_street`
treats a trailing numeric token in the address cell as `apartment_no`
("Miera 3 1" → apt 1), and `_parse_detail_page` does the same for the
detail "Street:" field. On parent-region *sell* listings the address
cell simply contains the settlement name ("Seda", "Smārdes pag.")
and the detail "Street:" field repeats it — the number is not there
to extract. Confirmed: all ten conflated ads have `street=''`-less
settlement text and no apt anywhere. The Šlokenbeka ads even carry
the real address only inside the comment text ("dzīvojamā mājā
'Šlokenbeka 5'").

## 2. Blast radius (measured, prod DB)

| Metric | Count |
|---|---|
| `ApartmentProperty` total / with ≥2 linked ads | 21,040 / 2,031 |
| Props whose linked ads carry ≥2 distinct apt_nos | **0** — the direct heuristic is blind; conflations hide behind missing data |
| Props (≥2 ads) with >1 distinct `floor` | **160** (7.9% of multi-ad props; audit estimated ~75 — that count used its own pair set) |
| Props with ≥2 same-deal ads whose seen-windows overlap | 233 any-overlap; **101 with ≥2-day overlap** (98 same-seller) |
| Props absorbing ≥3 ads on one `first_seen` day | 39 |
| Sale ads with a rent twin on a **different** prop | **650** across 622 sale-side props |
| — of those, props whose twins diverge to ≥2 targets | **4** = the conflated set (13910, 16037, 16071, 16072) |
| — props mirroring exactly 1 twin target | 618 (ordinary prop *duplication*, not conflation) |
| Reverse direction (rent prop → ≥2 distinct sale props) | 3 props (3420, 7016, 7470) — inspected: all same-unit reposts, i.e. ordinary duplication, not conflation |
| Ads in degenerate `street_no=''` blocks | 2,197/12,118 sale (18%), 1,258/11,671 rent (11%), concentrated in `* un rajons` districts |
| Props with `street_no=''` | 3,118/21,040 (15%) |
| Catch-all `district='Cits'` ads | 18 sale + 30 rent — cross-town street collisions possible |
| `street_no` shaped `N-M` (house-apt fused) | 26 sale + 52 rent ads |

The apt_no signal finds zero suspects; **twin divergence is the only
decisive detector available today** and it found exactly the known
set plus 16037. The 160-floor / 101-overlap / 39-bulk pools are the
review-appropriate suspect list (~330 props unioned).

## 3. Prevention design

### 3a. Matcher hardening (`property_matcher.py`, command)

1. **Cross-deal twin shortcut (primary fix).** In `_link_ad`, before
   block scoring: look up `ad.ad_id` in the sibling deal table
   (`all_objects`). If the twin is linked to a property and passes
   the same hard-reject gates (rooms equal, size ≤15%) → link to
   that property directly (status `auto`, or a new score marker).
   If the twin is linked but attributes conflict → `candidate`
   status against the twin's property (covers the 5
   attribute-conflict pairs — a seller may have repurposed the
   listing for a different unit). If the twin is unlinked, normal
   path. This is symmetric (rent↔sale) and idempotent under
   `--relink`. Note it only fires when the twin was scraped and
   linked first — ordering makes it a strong net, not a guarantee;
   the audit command (3c) is the backstop.

2. **Conflation alarms → demote auto to candidate.** In
   `match_property`, compute alongside the score:
   - `len(prop_nos) >= 2` — property already holds multiple unit
     numbers (self-reinforcing reject fix);
   - property holds ≥2 same-deal ads whose seen-windows already
     overlap (batch-absorption signature);
   - linked ads disagree on `floor` (unanimous-floor prop vs.
     dissenting new ad);
   - block degenerate: `street_no == ''` (settlement-level bucket)
     *and* ad has no apt_no *and* no twin evidence.
   Any alarm → cap decision at `candidate` regardless of score
   (auto-link only on decisive evidence: apt_no match or twin).
   Cheap: all inputs already loaded for scoring.

3. **Degenerate-block guard.** For `street_no=''` candidates,
   `street_name` is a town, not a street — same-name streets across
   the whole district merge into one bucket (and `Cits` districts
   can collide across towns). Require decisive evidence (twin or
   apt_no) for auto-link in such blocks, or treat `district+street`
   as unit-ambiguous by default. 18% of sale ads sit here.

4. **`N-M` street numbers.** 78 ads have `street_no` like `6-3`
   (`^\d+-\d+$`) — ss.com's house-apt fusion. Splitting these into
   `street_no=N` + `apartment_no=M` both fixes block fragmentation
   (these ads currently can't match siblings stored under `N`) and
   fabricates the missing apt evidence. Implement in
   `_split_street`/normalization; flag for review since `5k-1`-style
   corpus suffixes must not be touched (only the pure `\d+-\d+`
   shape).

5. **Comment Jaccard qualification.** Boilerplate identical across
   an agent's whole portfolio contributed +0.15 to every conflation.
   Only award the +0.15 when the similarity *discriminates* — e.g.
   skip it when the ad's comment is also ≥0.8-similar to ads on
   *other* candidate properties in the block (template reuse), or
   when the block's linked comments are mutually identical.

6. **Multi-candidate demotion.** When >1 candidate property survives
   hard rejects and the ad lacks apt_no, pick best but cap at
   candidate (ambiguity means the score is choosing, not evidence).

### 3b. `extract_apartment_no` recall

Scanned all 23,812 ad comments; current regexes hit 98. Phrases they
miss (counts = comments containing the shape):

| Pattern | Hits | Verdict |
|---|---|---|
| `кв. N` / `кв N` (Russian) | 13 | **Add** — clean (`кв\.\s*(\d{1,4})`) |
| `dz. N` without `nr` | 3 | Probably add after sample check (watch "dz. 3 ist.") |
| `apt. N` / `flat N` | 3 | Add EN `apt.`/`flat` bare-number form |
| `Nr. N` without dzīvokl- marker | 241 | Keep gated — too ambiguous alone (property/lot no.) |
| `квартира N` | 742 | **Do not add** — dominated by project series ("квартира 602", "467", "103" = series names) |
| `dzīvoklis N` bare | 1,205 | **Do not add** — series/count false positives; the marker-word requirement is correct |

Recommend: add `кв.`, `dz.` (with optional nr), `apt.`/`flat`
forms; consider a two-token-window rule (`dzīvokl\w*` … `nr.?\s*N`
within ~30 chars) to safely admit part of the 241 `Nr.` group. All
additions get unit tests against the false-positive classes above
(series numbers, room counts, "N dzīvokļu māja"). Expected gain is
modest (order of +1–2% coverage) — it tightens the hard reject but
cannot be the primary defense.

Not feasible: extracting apt numbers from the ss.com listing row
itself. `parse_results` already parses the trailing-number form via
`_split_street`; parent-region sell rows genuinely lack the token,
and the detail page "Street:" field repeats the settlement name.
(One unchecked avenue: whether ss.com detail pages ever expose a
dedicated flat-number field — verify on a live page before
investing; the attributes table parsed today has none.)

### 3c. Post-link audit + split workflow

New command `audit_property_links` (audit sibling to
`validate_sightings`), `--dry-run`-only by nature (read-only):

```
python manage.py audit_property_links [--type apartment]
```

Flags, in severity order:

1. **TWIN_DIVERGED** — linked ads' sibling-deal twins point to ≥2
   distinct properties (decisive; today: 4 props).
2. **APTNO_CONFLICT** — linked ads carry ≥2 distinct apt numbers
   (stored or comment-extracted; today: 0, guards the future).
3. **FLOOR_CONFLICT** — >1 distinct `floor` among linked ads
   (160 props — noisy, list for review not action).
4. **COEXISTING** — ≥2 same-deal ads with ≥2-day overlapping
   seen-windows, same seller (98 props).
5. **BULK_ABSORB** — ≥3 ads sharing one `first_seen` day (39 props).

Output: prop id, flag, evidence (ad_ids, apt_nos, twin targets).

**Split/relink workflow** — management command
`relink_property_ads` (writes; run deliberately, never by cron):

```
python manage.py relink_property_ads --twin-fix --dry-run
python manage.py relink_property_ads \
    --prop 13910 --ads tr_56869220,tr_56869274 --to-prop 1553
python manage.py relink_property_ads \
    --prop P --ads ... --to-new
```

- `--twin-fix`: for every linked ad whose sibling-deal twin sits on
  a different property and passes the twin hard-gates, re-point the
  FK (repairs all 650 split pairs; the emptied duplicate property
  dies via the existing `_delete_if_orphan`/`_vacate_property`
  semantics). Attribute-conflicting twins are listed, not moved.
- `--ads ... --to-prop/--to-new`: explicit reassignment for the
  flagged list; sets `property_match_status='manual'`, then
  `refresh_from_ads()` on both source and target, deleting the
  source if empty.
- Admin: add a "conflation flags" column/filter on the property
  changelist (annotated by the same checks) and show twin-divergence
  on the candidate review list so 13910-style manual approvals get
  stopped at the screen. Optionally a "Merge into property" admin
  action (currently missing — the audit's 618 dup props otherwise
  need per-ad moves).

### 3d. Remediation — the four conflated properties

Every move is determined by the `ad_id` twin — no judgement calls:

| Ad (sale table) | From prop | To prop | Evidence |
|---|---|---|---|
| tr_56869220 | 13910 | 1553 | rent twin apt 7, fl2/3, 40m² |
| tr_56869274 | 13910 | 1552 | rent twin apt 8, fl2/3, 47m² |
| tr_56869324 | 13910 | 1551 | rent twin apt 3, fl1/3, 41m² |
| tr_56868083 | 13910 | 1550 | rent twin apt 11, fl3/3, 40m² |
| tr_57743400 | 16071 | **5681** | rent twin — Saules **9** apt 1 (not Miera 3; audit's unit list was approximate) |
| tr_57743380 | 16071 | 5685 | rent twin Miera 3 apt 12, fl2/2 |
| tr_57743365 | 16071 | 5686 | rent twin Miera 3 apt 4, fl2/2 |
| tr_57743358 | 16071 | 5687 | rent twin Miera 3 apt 1, fl1/2 |
| tr_57743394 | 16072 | 5682 | rent twin Saules 4 apt 6, 63m² |
| tr_57743388 | 16072 | 5683 | rent twin Saules 4 apt 4, 62m² |
| tr_57784765 | 16037 | 5615 | rent twin Jaunpils `1 1`, same seller |
| tr_58047532 | 16037 | 7795 | rent twin Saulrieti 6, same seller |

After the moves all four props are empty → delete (or let
`refresh`/`_delete_if_orphan` handle it). `match_status='manual'`.

Caveat to eyeball during remediation: target prop **5615** already
holds sale ad tr_57784782 (linked at 0.85, no twin) — same seller,
same specs, plausibly the same unit reposted; keep but include in
the audit output. Also note tr_56869274's `manual` status: the
remediation is the second human decision on that ad — worth a
changelog comment.

The 618 single-target dup props and 5 attribute-conflict pairs are
the audit's separate merge queue, not conflation — `--twin-fix`
repairs them through the same mechanism (or the proposed merge
action); conflicts go to the review queue.

### 3e. Trade-offs and risks

- **More candidates, more singletons.** Every alarm trades auto-link
  volume for review-queue volume. Queue is currently empty; a one-off
  backlog of ~330 suspect props is reviewable. False *splits* cost
  less than false *merges* for stats, and are recoverable via
  merge/relink.
- **Twin shortcut trust.** `ad_id` equality is nearly decisive but
  not absolute — 5/641 twin pairs show attribute conflicts
  (repurposed listings). The hard-gate on rooms/size before the
  shortcut keeps those out of auto-link; residual risk is a
  same-fingerprint repurpose, which lands in candidate anyway under
  the alarms.
- **Ordering dependence.** The shortcut only helps when the sibling
  row exists and is already linked; a sale ad scraped weeks before
  its rent twin still conflates on first pass. Mitigation: the audit
  command catches it deterministically afterwards; scrapers could
  also enqueue a re-match for the older ad when a new twin arrives.
- **`--relink` behavior changes.** With the shortcut, `--relink`
  performs mass migration of sale ads onto twin properties (650
  moves) rather than re-choosing inside the block — that is the
  intended repair, but run it after the audit's dry-run, scoped
  (`--deal sale --type apartment`), with the histogram checked
  before committing. Emptied props auto-delete; verify the count
  matches the dry-run list.
- **`N-M` split** could mis-split genuine hyphenated numbering
  (`54k-2` corpus forms are excluded by the `\d+-\d+$` gate, but
  e.g. `6-3` might rarely be house 6 corpus 3). Small surface (78
  ads); make it produce a *candidate* apt_no, not a stored one, or
  restrict to blocks where props already carry matching apt numbers.
- **Coexistence false-positives.** Dual-listing of one unit by two
  agencies, or a repost whose old ad lingers ≥2 days, trips the
  COEXISTING alarm without being conflation — which is why alarms
  demote to review instead of rejecting.
- **`manual` status conflation.** `manual` currently means
  confirmed-link, rejected-candidate, admin-created-property *and*
  (proposed) audit-relinked. Consider a status (`'audit'`/`'split'`)
  or a `link_reason` field if distinguishing provenance matters.

## Implementation steps

### Phase 1 — Audit + remediation (read-mostly, one command)

1. `audit_property_links` reporting the five flags.
2. `relink_property_ads --twin-fix --dry-run`, review output, run.
3. Explicit moves for the 12 conflated ads (table in 3d); verify the
   four source props emptied and were deleted.

### Phase 2 — Matcher hardening

1. Twin shortcut in `_link_ad` + hard-gates.
2. Conflation alarms → candidate demotion.
3. Degenerate-block guard; multi-candidate demotion.
4. `_split_street` `N-M` handling; comment-Jaccard qualification.
5. `extract_apartment_no` additions (`кв.`, `dz.`, `apt.`/`flat`,
   windowed `Nr.`) with false-positive unit tests in
   `classified_ads/tests.py` (currently a stub — seed with the
   conflated-building fixtures).

### Phase 3 — Review surface

1. Property changelist conflation-flags filter/column; twin
   divergence shown on candidate rows.
2. Optional "Merge property" admin action for the 618 dup props.
3. Scheduled `audit_property_links` run (cron/next to the linking
   job); alert on TWIN_DIVERGED/APTNO_CONFLICT > 0.

## Rollback

All matcher changes are additive gates; reverting restores prior
scoring. Remediation moves only update `property` FKs and match
fields — the audit output (ad_id → previous property) is itself the
undo list. No ad or sighting data is touched.

## Success criteria

- `audit_property_links` reports TWIN_DIVERGED = 0 after Phase 1.
- A `link_ads_to_properties --relink --dry-run` on the hardened
  matcher produces zero new conflation alarms on the known buildings
  while keeping true-match auto-links (spot-check a repost cluster
  like `Chaka 133` and a pumpura-style dup cluster).
- The four (now-dissolved) props' ads sit on props 1550–1553,
  5615, 5681–5683, 5685–5687, 7795 with `manual` status.
- Candidate queue grows but auto-link volume stays within ~5% of the
  pre-change histogram on `--dry-run`.
