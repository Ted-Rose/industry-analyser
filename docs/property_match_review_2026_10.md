# Property duplicate-review report

Dataset: `/tmp/property_review_dataset.json` (ss.com classified ads → canonical properties).

> **Snapshot caveat**: counts reflect the prod DB as of 2026-10-05.
> Cross-deal duplicate pairs are still being created (~48 apt pairs
> in the 7 days to 2026-10-06) until the twin-shortcut fix in
> `docs/property_conflation_prevention_plan.md` lands — treat the
> pair lists as a queue that refills, not a closed set.

## Executive summary

| Set | Total | Assessment |
|---|---|---|
| cross_deal_pairs (same ss.com ad_id on 2 property rows) | 641 | 626 confirmed duplicates, 10 pairs involving 3 conflated properties, 5 with attribute conflicts |
| same_block_pairs (same building, score ≥0.45) | 4797 | HIGH 557, MEDIUM 972, LOW 3268 |
| unmatched_ads | 206 | 6 likely-same, 4 plausible, 26 unlikely, 170 no plausible match |

**Recommended merges: ~326 HIGH-confidence property clusters (557 pairs) + 626 cross-deal pairs.**

## Confidence criteria

- **Shared ad_id** (rent+sale rows of one listing): decisive.
- **Apt number** (stored or `dzīvoklis nr.` in comment): match = near-decisive; conflict = near-decisive against. In practice the matcher's hard-reject already removes conflicting-apt pairs, so no conflicts survive in this set.
- **Comment similarity** (token Jaccard): ≥0.8 strong; byte-identical decisive. Agent template reuse is mitigated by requiring corroboration.
- **Seller phone**: dataset phones are masked (`(+371)29-44-***`), so prefix overlap is corroborating only — collisions among agents are possible. The stored score already uses the *unmasked* phone.
- **Repost signature** (one side's last_seen ≈ other's first_seen, ≤30d): corroborating — delete-and-repost.
- **Coexistence** (>14d overlapping sighting windows): weak negative — could be dual-listing of the same unit.
- **Floor/land/project/floors agreement**: corroborating; floor conflict is a negative unless decisive evidence overrides (the canonical floor is a "best ad" pick and is noisy: ~1.5% of properties have internally inconsistent ad floors).
- **Price** (same-deal medians): >30% mismatch is a weak negative; within 10% weak positive.
- **Stored merged score**: ≥0.8 = the matcher's own auto-link band → strong; 0.45–0.8 merely candidate-grade.

## 1. Cross-deal pairs (same ad_id on two property rows)

641 pairs (629 apartment, 12 house). All shared ads have identical ss.com links (the two "different" links found are locale/region-slug variants of the same URL).

**626 CONFIRMED_DUP** — the rent-table row is nearly always flagged `is_sale_misclassified` (601 of 662 shared ads), i.e. a for-sale listing scraped from the rent section; its sale-table twin was matched to a *different* property row. Action: link the rent row to the sale row's property (or merge the two property rows).

**10 CONFLATED** — three properties absorbed sale ads for *multiple different units* (no apt_no on the sale ads, identical rooms/size, so the hard rejects never fired):

| Conflated prop | Address | Units inside | Single-unit props sharing ads |
|---|---|---|---|
| 13910 | Smārdes pag., Šlokenbeka 5 | apts 3/7/8/11 (1r, 40–47m², floors 1–3) | 1550, 1551, 1552, 1553 |
| 16071 | Seda, Miera 3 | apts 1/4/12 (3r/71m², floors 1–2) | 5681, 5685, 5686, 5687 |
| 16072 | Seda, Saules 4 | apts 4/6 (2r, 62–63m²) | 5682, 5683 |

Action: do NOT merge. Re-link each shared ad to the single-unit property and evict the foreign ads from the conflated property (which may dissolve entirely).

**5 ATTRIBUTE_CONFLICT** — same listing, but the rent and sale rows disagree (the ad was edited between scrapes, or scraped inconsistently):

| Pair | Address | Conflict |
|---|---|---|
| 1973 ↔ 19567 | Zaķusala Zakusalas bund 27 | tr_57844265 size 53.0vs69.0 |
| 5811 ↔ 16094 | Aizkraukles pag. Kalna 1 | tr_57623569 rooms 4vs2; tr_57623569 size 97.0vs48.0 |
| 8645 ↔ 12345 | Teika Kastranes 1 | tr_54912085 size 36.0vs18.0 |
| 18604 ↔ 20143 | Teika Kaukaza 11 | tr_57073862 floor 1vs2 |
| 840 ↔ 4937 | Skrunda Liela 10 | tr_57918083 size 36.0vs75.0 |

Action: same listing id/link, so still duplicates — but verify which attribute snapshot is correct before merging (e.g. tr_57623569: rent row says 4r/97m²/apt7, sale row says 2r/48m² — the seller may have repurposed the listing for a different unit).

## 2. Same-block pairs

### HIGH — 557 pairs in 326 mergeable clusters (recommended: merge/link)

| Prop A | Prop B | Type | Address | Score | Key evidence |
|---|---|---|---|---|---|
| 19770 | 20573 | apar | Āgenskalns Ranka d. 31 | 1.25 | shared apt_no 19; comment sim 0.66; same seller phone prefix; repost gap 21d; same floor |
| 18715 | 18734 | apar | Jelgava Lielā 25 | 1.10 | identical comment; same seller phone prefix; repost gap 1d; same floor |
| 20280 | 20652 | apar | Āgenskalns Ranka d. 9 | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19156 | 20026 | apar | Dobele un rajons Dobele  | 1.10 | identical comment; same seller phone prefix; repost gap 13d; same floor |
| 20026 | 20310 | apar | Dobele un rajons Dobele  | 1.10 | identical comment; same seller phone prefix; repost gap 9d; same floor |
| 18791 | 18818 | apar | Centrs Valmieras 13 | 1.10 | identical comment; same seller phone prefix; repost gap 1d; same floor |
| 19231 | 19355 | apar | Centrs Katrinas d. 6 | 1.10 | identical comment; same seller phone prefix; repost gap 10d; same floor |
| 18676 | 18744 | apar | Centrs Dzirnavu 27 | 1.10 | identical comment; same seller phone prefix; repost gap 7d; same floor |
| 10541 | 20624 | apar | Dreiliņi Valtera 1 | 1.10 | identical comment; same seller phone prefix; same floor |
| 20036 | 20691 | apar | Jelgava Pumpura 7 | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 20390 | 20391 | apar | Jelgava Pumpura 7 | 1.10 | identical comment; same seller phone prefix; same floor |
| 19008 | 19031 | apar | Sigulda Raiņa 1 | 1.10 | identical comment; same seller phone prefix; same floor; coexisted 31d |
| 19553 | 19841 | apar | Ķengarags Prushu 20 | 1.10 | identical comment; same seller phone prefix; repost gap 10d; same floor |
| 19749 | 19806 | apar | Valmiera un rajons -  | 1.10 | identical comment; same seller phone prefix; repost gap 2d; same floor |
| 19848 | 19992 | apar | Šampēteris-Pleskodāle Lielirbes 9a | 1.10 | identical comment; same seller phone prefix; same floor |
| 20595 | 20676 | apar | Purvciems Zhagatu 22 | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19263 | 19264 | apar | Rēzekne Atbrīvošanas aleja..  | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 18564 | 18565 | apar | Rēzekne Atbrīvošanas aleja..  | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19332 | 19333 | apar | Rēzekne Atbrīvošanas aleja..  | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19347 | 19348 | apar | Rēzekne Atbrīvošanas aleja..  | 1.10 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19060 | 20518 | apar | Liepas pag. Pāvila Rozīša 5 | 1.10 | same ad_id linked to both; identical comment; same seller phone prefix; repost gap 7d; same floor |
| 19194 | 19322 | apar | Mežciems Eizenshteina 57 | 1.10 | identical comment; same seller phone prefix; repost gap 11d; same floor |
| 20552 | 20553 | apar | Jelgava Pumpura 7 | 1.10 | comment Jaccard 1.00; same seller phone prefix; repost gap 0d; same floor |
| 19769 | 20295 | apar | Mežciems Bikernieku 255 | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 0d; same floor |
| 20253 | 20357 | apar | Cenas pag. Celtnieku 9 | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 4d; same floor |
| 19313 | 19685 | apar | Cēsis un rajons Cēsis  | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 13d; same floor |
| 19927 | 20118 | apar | Centrs Vilandes 8 | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 5d; same floor |
| 19635 | 19969 | apar | Pļavnieki Rudens 3 | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 3d; same floor |
| 20256 | 20469 | apar | Ķengarags Prushu 22/2 | 1.10 | comment Jaccard 0.99; same seller phone prefix; repost gap 11d; same floor |
| 20682 | 20683 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 18704 | 18848 | apar | Saulkrasti Liepu 1a | 1.10 | comment Jaccard 0.98; same seller phone prefix; repost gap 9d; same floor |
| 18688 | 18792 | apar | Jēkabpils un rajons Jēkabpils  | 1.10 | comment Jaccard 0.98; same seller phone prefix; repost gap 10d; same floor |
| 18567 | 18646 | apar | Centrs Stabu 15 | 1.10 | comment Jaccard 0.98; same seller phone prefix; repost gap 12d; same floor |
| 20678 | 20679 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 20681 | 20682 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 20681 | 20683 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 16641 | 19865 | apar | Vecrīga Pasta 6 | 1.10 | comment Jaccard 0.97; same seller phone prefix; same floor |
| 19969 | 20444 | apar | Pļavnieki Rudens 3 | 1.10 | comment Jaccard 0.97; same seller phone prefix; repost gap 11d; same floor |
| 18807 | 18886 | apar | Centrs Rupniecibas 7 | 1.10 | comment Jaccard 0.97; same seller phone prefix; repost gap 12d; same floor |
| 20678 | 20682 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.97; same seller phone prefix; same floor |
| 20679 | 20681 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.97; same seller phone prefix; same floor |
| 20678 | 20681 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 20679 | 20682 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 20679 | 20683 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 3175 | 19049 | apar | Vecrīga Kungu 25 | 1.10 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 12520 | 19935 | apar | Vecrīga Pasta 6 | 1.10 | comment Jaccard 0.96; same seller phone prefix; same floor; coexisted 51d |
| 20678 | 20683 | apar | Majori Viktorijas 5 | 1.10 | comment Jaccard 0.95; same seller phone prefix; same floor |
| 19251 | 19285 | apar | Āgenskalns Zellu 13 | 1.10 | comment Jaccard 0.94; same seller phone prefix; same floor; coexisted 76d |
| 13119 | 19339 | apar | Centrs Mīlenbaha 1 | 1.10 | comment Jaccard 0.94; same seller phone prefix; same floor; coexisted 43d |
| 19808 | 20214 | apar | Iļģuciems Vaidelotes 21 | 1.10 | comment Jaccard 0.93; same seller phone prefix; repost gap 13d; same floor |
| 19523 | 19887 | apar | Jūrmala Perkona 3 | 1.10 | comment Jaccard 0.92; same seller phone prefix; repost gap 10d; same floor |
| 19559 | 19813 | apar | Iļģuciems Lidonu 6a | 1.10 | comment Jaccard 0.92; same seller phone prefix; repost gap 1d; same floor |
| 18602 | 18716 | apar | Aizkraukle un rajons Aizkraukles  | 1.10 | comment Jaccard 0.91; same seller phone prefix; repost gap 12d; same floor |
| 18886 | 18941 | apar | Centrs Rupniecibas 7 | 1.10 | comment Jaccard 0.89; same seller phone prefix; repost gap 7d; same floor |
| 19310 | 20466 | apar | Āgenskalns Zellu 13 | 1.10 | comment Jaccard 0.88; same seller phone prefix; same floor |
| 19493 | 20341 | apar | Bauska un rajons Bauska  | 1.10 | comment Jaccard 0.87; same seller phone prefix; repost gap 1d; same floor |
| 18814 | 18815 | apar | Iļģuciems Bullu 20 | 1.10 | comment Jaccard 0.87; same seller phone prefix; same floor |
| 19088 | 19100 | apar | Centrs Artilerijas 21 | 1.10 | comment Jaccard 0.86; same seller phone prefix; repost gap 0d; same floor |
| 20394 | 20395 | apar | Centrs Chaka 133 | 1.10 | comment Jaccard 0.86; same seller phone prefix; same floor |
| 19310 | 19951 | apar | Āgenskalns Zellu 13 | 1.10 | comment Jaccard 0.86; same seller phone prefix; same floor |
| 19091 | 19100 | apar | Centrs Artilerijas 21 | 1.10 | comment Jaccard 0.81; same seller phone prefix; repost gap 0d; same floor |
| 19156 | 20310 | apar | Dobele un rajons Dobele  | 1.00 | identical comment; same seller phone prefix; same floor |
| 19352 | 20693 | apar | Āgenskalns Ranka d. 34 | 1.00 | identical comment; same seller phone prefix; repost gap 26d; same floor |
| 19984 | 19985 | apar | Centrs Eksporta 8 | 1.00 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 18591 | 18676 | apar | Centrs Dzirnavu 27 | 1.00 | identical comment; same seller phone prefix; repost gap 15d; same floor |
| 18591 | 18744 | apar | Centrs Dzirnavu 27 | 1.00 | identical comment; same seller phone prefix; repost gap 23d; same floor |
| 19170 | 19419 | apar | Jugla Juglas 1 | 1.00 | identical comment; same seller phone prefix; repost gap 15d; same floor |
| 17456 | 20629 | apar | Ķengarags Vishku 15 | 1.00 | identical comment; same seller phone prefix; same floor |
| 19404 | 19954 | apar | Rēzekne un rajons Rezekne  | 1.00 | identical comment; same seller phone prefix; repost gap 16d; same floor |
| 19844 | 20159 | apar | Rēzekne un rajons Rezekne  | 1.00 | identical comment; same seller phone prefix; repost gap 16d; same floor |
| 19171 | 19418 | apar | Mežciems Juglas 1 | 1.00 | identical comment; same seller phone prefix; repost gap 15d; same floor |
| 18883 | 20706 | apar | Purvciems Burtnieku 33 | 1.00 | same ad_id linked to both; identical comment; same seller phone prefix; same floor |
| 19225 | 19415 | apar | Zolitūde Lejina 14 | 1.00 | identical comment; same seller phone prefix; repost gap 15d; same floor |
| 12141 | 19096 | apar | Salaspils l. t. Daugavmalas 34 | 1.00 | same ad_id linked to both; identical comment; same seller phone prefix; repost gap 26d; same floor |
| 19311 | 19504 | apar | Jugla Baltezera 10a | 1.00 | identical comment; same seller phone prefix; repost gap 19d; same floor |
| 19311 | 20217 | apar | Jugla Baltezera 10a | 1.00 | identical comment; same seller phone prefix; same floor |
| 19504 | 20217 | apar | Jugla Baltezera 10a | 1.00 | identical comment; same seller phone prefix; same floor |
| 18801 | 19818 | apar | Vārves pag. Zūras 4 | 1.00 | same ad_id linked to both; identical comment; same seller phone prefix; repost gap 18d; same floor |
| 4446 | 5650 | hous | Saulkrasti Mazā Neibādes 4 | 1.00 | comment Jaccard 1.00; same seller phone prefix |
| 20207 | 20660 | apar | Purvciems Ilukstes 109 | 1.00 | comment Jaccard 0.99; same seller phone prefix; repost gap 29d; same floor |
| 2398 | 18990 | apar | Centrs Stabu 30 | 1.00 | comment Jaccard 0.99; same seller phone prefix; same floor |
| 18622 | 19077 | apar | Centrs Stabu 18b | 1.00 | comment Jaccard 0.99; same seller phone prefix; same floor |
| 20678 | 20680 | apar | Majori Viktorijas 5 | 1.00 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 19132 | 19769 | apar | Mežciems Bikernieku 255 | 1.00 | comment Jaccard 0.98; same seller phone prefix; repost gap 29d; same floor |
| 19132 | 20295 | apar | Mežciems Bikernieku 255 | 1.00 | comment Jaccard 0.98; same seller phone prefix; repost gap 30d; same floor |
| 19618 | 20207 | apar | Purvciems Ilukstes 109 | 1.00 | comment Jaccard 0.98; same seller phone prefix; repost gap 27d; same floor |
| 20679 | 20680 | apar | Majori Viktorijas 5 | 1.00 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 12535 | 18879 | apar | Vecrīga M. Smilshu 12 | 1.00 | same ad_id linked to both; comment Jaccard 0.98; same seller phone prefix; same floor |
| 18828 | 19015 | apar | Centrs Terbatas 72 | 1.00 | comment Jaccard 0.98; same seller phone prefix; same floor |
| 19618 | 20660 | apar | Purvciems Ilukstes 109 | 1.00 | comment Jaccard 0.97; same seller phone prefix; same floor |
| 18762 | 18891 | apar | Liepāja Mālu 7 | 1.00 | comment Jaccard 0.97; same seller phone prefix; repost gap 16d; same floor |
| 20680 | 20682 | apar | Majori Viktorijas 5 | 1.00 | comment Jaccard 0.97; same seller phone prefix; same floor |
| 19278 | 19945 | apar | Valmiera un rajons Valmiera  | 1.00 | comment Jaccard 0.97; same seller phone prefix; repost gap 28d; same floor |
| 20680 | 20681 | apar | Majori Viktorijas 5 | 1.00 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 19635 | 20444 | apar | Pļavnieki Rudens 3 | 1.00 | comment Jaccard 0.96; same seller phone prefix; same floor |
| 3549 | 19078 | apar | Liepāja Klaipedas 104 | 1.00 | comment Jaccard 0.96; same seller phone prefix; repost gap 22d; same floor |
| 20680 | 20683 | apar | Majori Viktorijas 5 | 1.00 | comment Jaccard 0.95; same seller phone prefix; same floor |
| 19148 | 19553 | apar | Ķengarags Prushu 20 | 1.00 | comment Jaccard 0.95; same seller phone prefix; repost gap 21d; same floor |
| 19148 | 19841 | apar | Ķengarags Prushu 20 | 1.00 | comment Jaccard 0.95; same seller phone prefix; same floor |
| 19951 | 20466 | apar | Āgenskalns Zellu 13 | 1.00 | comment Jaccard 0.93; same seller phone prefix; repost gap 26d; same floor |
| 19183 | 19748 | apar | Centrs Brivibas 104 | 1.00 | comment Jaccard 0.92; same seller phone prefix; repost gap 24d; same floor |
| 19502 | 20174 | apar | Pļavnieki Jasmuizhas 24 | 1.00 | comment Jaccard 0.92; same seller phone prefix; repost gap 30d; same floor |
| 19218 | 19858 | apar | Centrs Mīlenbaha 1 | 1.00 | comment Jaccard 0.91; same seller phone prefix; repost gap 28d; same floor |
| 19189 | 19502 | apar | Pļavnieki Jasmuizhas 24 | 1.00 | comment Jaccard 0.90; same seller phone prefix; repost gap 19d; same floor |
| 19189 | 20174 | apar | Pļavnieki Jasmuizhas 24 | 1.00 | comment Jaccard 0.89; same seller phone prefix; same floor |
| 18807 | 18941 | apar | Centrs Rupniecibas 7 | 1.00 | comment Jaccard 0.88; same seller phone prefix; repost gap 19d; same floor |
| 19880 | 20256 | apar | Ķengarags Prushu 22/2 | 1.00 | comment Jaccard 0.86; same seller phone prefix; repost gap 20d; same floor |
| 19880 | 20469 | apar | Ķengarags Prushu 22/2 | 1.00 | comment Jaccard 0.85; same seller phone prefix; same floor |
| 20462 | 20651 | apar | Čiekurkalns Chiekurkalna 2. cr..  | 1.00 | comment Jaccard 0.85; same seller phone prefix; repost gap 15d; same floor |
| 16538 | 20496 | apar | Krasta r-ns Kridenera d. 4 | 1.00 | comment Jaccard 0.80; same seller phone prefix; same floor |
| 16121 | 19539 | apar | Centrs Sadovnikova 30 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 10284 | 20551 | apar | Centrs Brivibas 68 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 8435 | 1904 | apar | Centrs Brivibas 148 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 10541 | 20081 | apar | Dreiliņi Valtera 1 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 10541 | 20084 | apar | Dreiliņi Valtera 1 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 35d |
| 10535 | 20080 | apar | Dreiliņi Valtera 1 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 20081 | 20084 | apar | Dreiliņi Valtera 1 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 20084 | 20624 | apar | Dreiliņi Valtera 1 | 0.95 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 20659 | 20670 | apar | Šampēteris-Pleskodāle Lielirbes 15 | 0.95 | comment Jaccard 1.00; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 12596 | 20184 | apar | Ziepniekkalns Bauskas 97 | 0.95 | comment Jaccard 1.00; same seller phone prefix; FLOOR CONFLICT; coexisted 30d |
| 2566 | 5006 | hous | Dārzciems Plauzhu 4 | 0.95 | comment Jaccard 1.00; same seller phone prefix; coexisted 49d |
| 18911 | 18912 | apar | Centrs Barona 24/26 | 0.95 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 19836 | 19895 | apar | Jelgava Pumpura 7 | 0.95 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 19864 | 19865 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 18944 | 19041 | apar | Mārupes pag. Malduguņu 6 | 0.95 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 19d |
| 19573 | 20191 | apar | Centrs Brivibas 91 | 0.95 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 37d |
| 19713 | 19791 | apar | Āgenskalns Sabiles 15b | 0.95 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 76d |
| 16641 | 19864 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT |
| 19038 | 18951 | apar | Vecmīlgrāvis Skuju 29 | 0.95 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT; coexisted 19d |
| 19573 | 19574 | apar | Centrs Brivibas 91 | 0.95 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 64d |
| 19574 | 20191 | apar | Centrs Brivibas 91 | 0.95 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 37d |
| 10207 | 20230 | apar | Centrs Gertrudes 56 | 0.95 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 19595 | 20014 | apar | Ziepniekkalns Malu 18 | 0.95 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 19863 | 19866 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 19935 | 20271 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 12424 | 20698 | apar | Vaivari Vēju 5a | 0.95 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT |
| 12520 | 20271 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 19837 | 19895 | apar | Jelgava Pumpura 7 | 0.95 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT |
| 19836 | 19837 | apar | Jelgava Pumpura 7 | 0.95 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT |
| 12890 | 19993 | apar | Šampēteris-Pleskodāle Lielirbes 9a | 0.95 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT |
| 19943 | 20662 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |
| 16641 | 19863 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |
| 12524 | 12520 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 19974 | 20661 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.90; same seller phone prefix; FLOOR CONFLICT; coexisted 15d |
| 19972 | 19974 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.89; same seller phone prefix; FLOOR CONFLICT |
| 7410 | 18973 | apar | Mežaparks Viestura pr. 95 | 0.95 | comment Jaccard 0.89; same seller phone prefix; repost gap 3d; same floor |
| 12524 | 19297 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.88; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 12524 | 19935 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.87; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 12524 | 20271 | apar | Vecrīga Pasta 6 | 0.95 | comment Jaccard 0.86; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 1891 | 19004 | apar | Centrs Vagonu 22 | 0.95 | comment Jaccard 0.84; same seller phone prefix; FLOOR CONFLICT |
| 6339 | 18814 | apar | Iļģuciems Bullu 20 | 0.95 | comment Jaccard 0.83; same seller phone prefix; FLOOR CONFLICT |
| 19538 | 20243 | apar | Centrs Pulkv. Briezha 10 | 0.95 | comment Jaccard 0.83; same seller phone prefix; FLOOR CONFLICT |
| 3345 | 18875 | apar | Centrs Matisa 46 | 0.95 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT |
| 19004 | 19020 | apar | Centrs Vagonu 22 | 0.95 | comment Jaccard 0.80; same seller phone prefix; repost gap 6d; FLOOR CONFLICT |
| 19229 | 19444 | apar | Ludza un rajons Ludza  | 0.95 | comment sim 0.79; same seller phone prefix; repost gap 11d; same floor |
| 18941 | 19032 | apar | Centrs Rupniecibas 7 | 0.95 | comment sim 0.79; same seller phone prefix; repost gap 12d; same floor |
| 18681 | 19518 | apar | Ogre un rajons Ogre  | 0.95 | comment sim 0.78; same seller phone prefix; repost gap 0d; same floor |
| 19894 | 20391 | apar | Jelgava Pumpura 7 | 0.95 | comment sim 0.77; same seller phone prefix; same floor |
| 19494 | 19495 | apar | Teika Kaukaza 11 | 0.95 | comment sim 0.76; same seller phone prefix; same floor; coexisted 64d |
| 19088 | 19091 | apar | Centrs Artilerijas 21 | 0.95 | comment sim 0.74; same seller phone prefix; repost gap 0d; same floor |
| 18819 | 20077 | apar | Rēzekne un rajons Rezekne  | 0.95 | comment sim 0.73; same seller phone prefix; repost gap 5d; same floor |
| 19675 | 20023 | apar | Tukums un rajons Tukums  | 0.95 | comment sim 0.72; same seller phone prefix; repost gap 6d; same floor |
| 20251 | 20615 | apar | Dzintari Turaidas 17 | 0.95 | comment sim 0.71; same seller phone prefix; same floor |
| 19433 | 20231 | apar | Ādažu nov. Ūbeļu 3 | 0.95 | comment sim 0.70; same seller phone prefix; repost gap 8d; same floor |
| 19172 | 19281 | apar | Jēkabpils un rajons Salas pag.  | 0.95 | comment sim 0.70; same seller phone prefix; repost gap 3d; same floor |
| 18937 | 18975 | apar | Ventspils Lielais prospekts ..  | 0.95 | comment sim 0.68; same seller phone prefix; repost gap 1d; same floor |
| 20396 | 20399 | apar | Centrs Chaka 133 | 0.95 | comment sim 0.65; same seller phone prefix; same floor |
| 19065 | 19090 | apar | Teika Kaukaza 11 | 0.95 | comment sim 0.63; same seller phone prefix; same floor; coexisted 55d |
| 19897 | 19998 | apar | Rēzekne un rajons Rezekne  | 0.95 | comment sim 0.62; same seller phone prefix; repost gap 5d; same floor |
| 18997 | 19013 | apar | Rēzekne un rajons Rezekne  | 0.95 | comment sim 0.60; same seller phone prefix; same floor; coexisted 20d |
| 19898 | 19565 | apar | Daugavpils Vienibas 42 | 0.95 | comment sim 0.59; same seller phone prefix; repost gap 10d; same floor |
| 18605 | 20163 | apar | Teika Kaukaza 11 | 0.95 | same ad_id linked to both; comment sim 0.59; same seller phone prefix; repost gap 8d; same floor |
| 18562 | 18652 | apar | Jūrmala Lauku 35 | 0.95 | comment sim 0.57; same seller phone prefix; repost gap 11d; same floor |
| 18641 | 18648 | apar | Centrs Visvalzha 3 | 0.95 | comment sim 0.56; same seller phone prefix; repost gap 0d; same floor |
| 19670 | 19939 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | comment sim 0.56; same seller phone prefix; repost gap 6d; same floor |
| 9153 | 18598 | apar | Daugavpils un rajons Cietokšņa 27 | 0.95 | comment sim 0.55; same seller phone prefix; repost gap 7d; same floor |
| 18957 | 18979 | apar | Centrs Valmieras 13 | 0.95 | comment sim 0.53; same seller phone prefix; repost gap 4d; same floor |
| 19242 | 18577 | apar | Rēzekne un rajons Rezekne  | 0.95 | comment sim 0.52; same seller phone prefix; repost gap 0d; same floor |
| 20267 | 20334 | apar | Teika Brivibas g. 239 | 0.95 | same seller phone prefix; repost gap 4d; same floor |
| 18931 | 19522 | apar | Šampēteris-Pleskodāle Zalves 35 | 0.95 | same seller phone prefix; same floor; coexisted 17d |
| 19828 | 20122 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | same seller phone prefix; repost gap 5d; same floor |
| 18557 | 18591 | apar | Centrs Dzirnavu 27 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 18872 | 19071 | apar | Centrs Lachplesha 111 | 0.95 | same seller phone prefix; same floor |
| 20180 | 12457 | apar | Vecmīlgrāvis Dombrovska 9b | 0.95 | same seller phone prefix; repost gap 8d; same floor |
| 20107 | 20515 | apar | Teika Brivibas g. 201 | 0.95 | same seller phone prefix; same floor |
| 19794 | 19795 | apar | Centrs Gertrudes 55a | 0.95 | same seller phone prefix; same floor |
| 20069 | 20688 | apar | Teika Brivibas g. 201 | 0.95 | same seller phone prefix; same floor |
| 20276 | 20561 | apar | Teika Brivibas g. 201 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 19837 | 20036 | apar | Jelgava Pumpura 7 | 0.95 | same seller phone prefix; same floor |
| 18993 | 20424 | apar | Centrs Klusa 20 | 0.95 | same ad_id linked to both; same seller phone prefix; repost gap 6d; same floor |
| 18666 | 18683 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | same seller phone prefix; repost gap 1d; same floor |
| 18604 | 18605 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 17097 | 20283 | apar | Āgenskalns Nomales 7 | 0.95 | same seller phone prefix; repost gap 1d; same floor |
| 17772 | 19652 | apar | Torņakalns Bauskas 15 | 0.95 | same seller phone prefix; repost gap 8d; same floor |
| 18688 | 19536 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | same seller phone prefix; same floor |
| 18792 | 19536 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | same seller phone prefix; repost gap 10d; same floor |
| 20303 | 20711 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; same floor |
| 18604 | 20163 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; repost gap 9d; same floor |
| 19494 | 20143 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; same floor; coexisted 58d |
| 2281 | 19021 | apar | Āgenskalns Valentina 16 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 20224 | 20521 | apar | Jelgava Raiņa 14 | 0.95 | same seller phone prefix; repost gap 12d; same floor |
| 19495 | 20143 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; same floor; coexisted 58d |
| 19066 | 19123 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 13885 | 18738 | apar | Saulkrasti Liepu 1a | 0.95 | same seller phone prefix; same floor |
| 19066 | 20303 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; same floor; coexisted 49d |
| 19066 | 20711 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; same floor |
| 18634 | 18706 | apar | Jēkabpils un rajons Jēkabpils  | 0.95 | same seller phone prefix; repost gap 6d; same floor |
| 20570 | 20573 | apar | Āgenskalns Ranka d. 31 | 0.95 | same seller phone prefix; same floor |
| 19509 | 19753 | apar | Valmiera un rajons -  | 0.95 | same seller phone prefix; repost gap 8d; same floor |
| 19002 | 19004 | apar | Centrs Vagonu 22 | 0.95 | same seller phone prefix; same floor |
| 19488 | 19669 | apar | Jelgava Meiju ceļš 30 | 0.95 | same seller phone prefix; repost gap 5d; same floor |
| 19123 | 20303 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 19123 | 20711 | apar | Teika Kaukaza 11 | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 19004 | 19103 | apar | Centrs Vagonu 22 | 0.95 | same seller phone prefix; same floor |
| 18592 | 19405 | apar | Ventspils Siguldas 21 | 0.95 | same seller phone prefix; repost gap 12d; same floor |
| 19002 | 19103 | apar | Centrs Vagonu 22 | 0.95 | same seller phone prefix; same floor |
| 19705 | 20285 | apar | Stopiņu nov. Rīgas 14 | 0.95 | same seller phone prefix; repost gap 2d; same floor |
| 19062 | 19112 | apar | Āgenskalns Ventspils 63c | 0.95 | same seller phone prefix; repost gap 0d; same floor |
| 11283 | 20671 | apar | Latgales priekšpilsēta Katolu 9 | 0.93 | identical comment; same seller phone prefix; repost gap 0d; same floor |
| 19863 | 19864 | apar | Vecrīga Pasta 6 | 0.93 | comment Jaccard 0.93; same seller phone prefix; same floor; coexisted 67d |
| 16641 | 19866 | apar | Vecrīga Pasta 6 | 0.93 | comment Jaccard 0.93; same seller phone prefix; same floor |
| 12322 | 20561 | apar | Teika Brivibas g. 201 | 0.93 | comment Jaccard 0.90; same seller phone prefix; same floor |
| 19065 | 19066 | apar | Teika Kaukaza 11 | 0.93 | comment Jaccard 0.85; same seller phone prefix; same floor; coexisted 56d |
| 18999 | 19110 | apar | Centrs Baznicas 34 | 0.90 | identical comment; same seller phone prefix; repost gap 22d; same floor |
| 19624 | 20377 | apar | Cēsis un rajons Līgatnes pag.  | 0.90 | comment Jaccard 0.96; same seller phone prefix; repost gap 14d; same floor |
| 19199 | 19325 | apar | Āgenskalns Ranka d. 34 | 0.90 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT; coexisted 76d |
| 19331 | 20275 | apar | Centrs Birznieka-Upisha 2.. | 0.90 | comment Jaccard 0.87; same seller phone prefix; same floor |
| 19693 | 20094 | apar | Cēsis un rajons Līgatne  | 0.90 | comment sim 0.72; same seller phone prefix; repost gap 10d; same floor |
| 19062 | 19084 | apar | Āgenskalns Ventspils 63c | 0.90 | same seller phone prefix; repost gap 0d; same floor |
| 19513 | 19667 | apar | Centrs Stabu 15 | 0.90 | same seller phone prefix; repost gap 5d; same floor |
| 18849 | 1904 | apar | Centrs Brivibas 148 | 0.90 | same seller phone prefix; same floor |
| 19084 | 19112 | apar | Āgenskalns Ventspils 63c | 0.90 | same seller phone prefix; repost gap 0d; same floor |
| 13339 | 20460 | apar | Jūrmala Dubultu pr. 101 | 0.88 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 52d |
| 11838 | 20634 | apar | Pļavnieki Dravnieku 3 K-3  | 0.88 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 10211 | 20608 | apar | Centrs Terbatas 78a | 0.88 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT |
| 20124 | 20165 | apar | Sigulda Institūta 1 | 0.88 | comment Jaccard 0.87; same seller phone prefix; same floor; coexisted 30d |
| 10320 | 19399 | apar | Centrs Stabu 59 | 0.88 | comment Jaccard 0.80; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 19341 | 19826 | apar | Mārupes pag. Silaputniņu 13 | 0.88 | same seller phone prefix; same floor; coexisted 67d |
| 59 | 18984 | apar | Āgenskalns Nometnu 62 | 0.85 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 25d |
| 10234 | 14076 | apar | Centrs Vashingtona pl. 2 | 0.85 | identical comment; same seller phone prefix; same floor |
| 10387 | 19564 | apar | Centrs Lachplesha 36 | 0.85 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 28d |
| 20081 | 20624 | apar | Dreiliņi Valtera 1 | 0.85 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 18944 | 19097 | apar | Mārupes pag. Malduguņu 6 | 0.85 | identical comment; same seller phone prefix; repost gap 28d; FLOOR CONFLICT |
| 19436 | 20714 | apar | Imanta Akaciju 2f | 0.85 | identical comment; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 14352 | 19711 | apar | Stopiņu nov. Rīgas 14 | 0.85 | identical comment; same seller phone prefix; repost gap 30d; FLOOR CONFLICT |
| 4970 | 4983 | hous | Daugmales pag. Jaunāraji  | 0.85 | same ad_id linked to both; comment Jaccard 1.00; repost gap 0d; same floors+land |
| 4976 | 5005 | hous | Drabešu pag. LācīšiPuķuzirņu 11 | 0.85 | same ad_id linked to both; comment Jaccard 1.00; repost gap 0d; same floors+land |
| 4975 | 4999 | hous | Ģibuļu pag. KraujasPriežkalni  | 0.85 | same ad_id linked to both; comment Jaccard 1.00; repost gap 0d; same floors+land |
| 4968 | 4978 | hous | Suntažu pag. SuntažiStacija  | 0.85 | same ad_id linked to both; comment Jaccard 1.00; repost gap 0d; same floors+land |
| 4972 | 4991 | hous | Valteri Lazdu 6 | 0.85 | same ad_id linked to both; comment Jaccard 1.00; repost gap 0d; same floors+land |
| 13868 | 20669 | apar | Šampēteris-Pleskodāle Lielirbes 15 | 0.85 | comment Jaccard 1.00; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 1891 | 18844 | apar | Centrs Vagonu 22 | 0.85 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 14483 | 19595 | apar | Ziepniekkalns Malu 18 | 0.85 | comment Jaccard 0.99; same seller phone prefix; same floor; coexisted 44d |
| 13163 | 19817 | apar | Centrs Vashingtona pl. 2 | 0.85 | comment Jaccard 0.99; same seller phone prefix; same floor; coexisted 39d |
| 19041 | 19097 | apar | Mārupes pag. Malduguņu 6 | 0.85 | comment Jaccard 0.98; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 19038 | 19127 | apar | Vecmīlgrāvis Skuju 29 | 0.85 | comment Jaccard 0.97; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 19127 | 18951 | apar | Vecmīlgrāvis Skuju 29 | 0.85 | comment Jaccard 0.97; same seller phone prefix; repost gap 27d; FLOOR CONFLICT |
| 18587 | 18721 | apar | Centrs Cesu 9 | 0.85 | comment Jaccard 0.97; same seller phone prefix; repost gap 20d; FLOOR CONFLICT |
| 19972 | 20661 | apar | Vecrīga Pasta 6 | 0.85 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 19865 | 19866 | apar | Vecrīga Pasta 6 | 0.85 | comment Jaccard 0.94; same seller phone prefix; same floor; coexisted 51d |
| 19164 | 19934 | apar | Vecrīga Pasta 6 | 0.85 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |
| 19016 | 19067 | apar | Centrs Terbatas 72 | 0.85 | comment Jaccard 0.91; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 16072 | 20087 | apar | Valka un rajons Seda  | 0.85 | comment Jaccard 0.88; same seller phone prefix; same floor |
| 19754 | 20552 | apar | Jelgava Pumpura 7 | 0.85 | comment Jaccard 0.88; same seller phone prefix; FLOOR CONFLICT |
| 19754 | 20553 | apar | Jelgava Pumpura 7 | 0.85 | comment Jaccard 0.87; same seller phone prefix; FLOOR CONFLICT |
| 7711 | 19011 | apar | Šampēteris-Pleskodāle Lielirbes 15 | 0.85 | comment Jaccard 0.82; same seller phone prefix; FLOOR CONFLICT |
| 18527 | 18705 | apar | Centrs Stabu 70 | 0.85 | comment sim 0.79; same seller phone prefix; repost gap 22d; same floor |
| 18846 | 19042 | apar | Teika Zemgala 77 | 0.85 | comment sim 0.79; same seller phone prefix; same floor |
| 19894 | 20390 | apar | Jelgava Pumpura 7 | 0.85 | comment sim 0.77; same seller phone prefix; same floor |
| 18886 | 19032 | apar | Centrs Rupniecibas 7 | 0.85 | comment sim 0.73; same seller phone prefix; repost gap 19d; same floor |
| 18807 | 19032 | apar | Centrs Rupniecibas 7 | 0.85 | comment sim 0.73; same seller phone prefix; same floor |
| 19200 | 20410 | apar | Rēzekne un rajons Rezekne  | 0.85 | comment sim 0.72; same seller phone prefix; same floor |
| 19268 | 19915 | apar | Centrs Pulkv. Briezha 10 | 0.85 | comment sim 0.69; same seller phone prefix; repost gap 28d; same floor |
| 20428 | 20530 | apar | Centrs Pernavas 39 | 0.85 | comment sim 0.68; same seller phone prefix; repost gap 15d; same floor |
| 16945 | 20476 | apar | Daugavpils Cialkovska 5 | 0.85 | comment sim 0.64; same seller phone prefix; repost gap 22d; same floor |
| 19228 | 20054 | apar | Āgenskalns Zellu 13 | 0.85 | comment sim 0.64; same seller phone prefix; same floor |
| 19160 | 19758 | apar | Rēzekne un rajons Rezekne  | 0.85 | comment sim 0.60; same seller phone prefix; repost gap 27d; same floor |
| 19462 | 20077 | apar | Rēzekne un rajons Rezekne  | 0.85 | comment sim 0.54; same seller phone prefix; repost gap 19d; same floor |
| 18819 | 19462 | apar | Rēzekne un rajons Rezekne  | 0.85 | comment sim 0.53; same seller phone prefix; repost gap 14d; same floor |
| 18777 | 20441 | apar | Torņakalns Bauskas 17 | 0.85 | comment sim 0.52; same seller phone prefix; same floor |
| 15756 | 20612 | apar | Olaine Dalbes 8 | 0.85 | comment sim 0.50; same seller phone prefix; same floor |
| 19151 | 20126 | apar | Gulbene un rajons Gulbene  | 0.85 | same seller phone prefix; same floor |
| 13372 | 20704 | apar | Grobiņa Celtnieku 40 | 0.85 | same seller phone prefix; repost gap 15d; same floor |
| 20401 | 20675 | apar | Purvciems Nicgales 40 | 0.85 | same seller phone prefix; repost gap 15d; same floor |
| 19122 | 19997 | apar | Torņakalns Apshu 4 | 0.85 | same seller phone prefix; same floor |
| 19973 | 20445 | apar | Centrs Chaka 133 | 0.85 | same seller phone prefix; repost gap 26d; same floor |
| 18557 | 18676 | apar | Centrs Dzirnavu 27 | 0.85 | same seller phone prefix; repost gap 15d; same floor |
| 18557 | 18744 | apar | Centrs Dzirnavu 27 | 0.85 | same seller phone prefix; repost gap 23d; same floor |
| 19895 | 20553 | apar | Jelgava Pumpura 7 | 0.85 | same seller phone prefix; same floor |
| 19895 | 20552 | apar | Jelgava Pumpura 7 | 0.85 | same seller phone prefix; same floor |
| 19466 | 20020 | apar | Jēkabpils un rajons Jēkabpils  | 0.85 | same seller phone prefix; repost gap 14d; same floor |
| 18824 | 18925 | apar | Centrs Rupniecibas 7 | 0.85 | same seller phone prefix; repost gap 17d; same floor |
| 18652 | 18866 | apar | Jūrmala Lauku 35 | 0.85 | same seller phone prefix; repost gap 19d; same floor |
| 19837 | 20691 | apar | Jelgava Pumpura 7 | 0.85 | same seller phone prefix; same floor |
| 18562 | 18866 | apar | Jūrmala Lauku 35 | 0.85 | same seller phone prefix; same floor |
| 9200 | 18782 | apar | Valmiera un rajons Bērzaines pag.  | 0.85 | same seller phone prefix; repost gap 26d; same floor |
| 19373 | 19901 | apar | Limbaži un rajons Limbaži  | 0.85 | same seller phone prefix; repost gap 18d; same floor |
| 18894 | 29 | apar | Āgenskalns Lielirbes 15 | 0.85 | same seller phone prefix; same floor |
| 17983 | 20009 | apar | Jelgava Paula Lejiņa 13 | 0.85 | same seller phone prefix; repost gap 3d; same floor |
| 19019 | 19062 | apar | Āgenskalns Ventspils 63c | 0.85 | same seller phone prefix; repost gap 15d; same floor |
| 19297 | 19874 | apar | Vecrīga Pasta 6 | 0.85 | same seller phone prefix; same floor |
| 19326 | 19764 | apar | Centrs Pulkv. Briezha 10 | 0.85 | same seller phone prefix; repost gap 17d; same floor |
| 19145 | 20368 | apar | Cēsis un rajons Līgatne  | 0.85 | same seller phone prefix; same floor |
| 19770 | 20570 | apar | Āgenskalns Ranka d. 31 | 0.85 | same seller phone prefix; repost gap 21d; same floor |
| 18997 | 19366 | apar | Rēzekne un rajons Rezekne  | 0.85 | same seller phone prefix; repost gap 18d; same floor |
| 19665 | 20150 | apar | Rēzekne un rajons Rezekne  | 0.85 | same seller phone prefix; repost gap 23d; same floor |
| 19013 | 19366 | apar | Rēzekne un rajons Rezekne  | 0.85 | same seller phone prefix; repost gap 17d; same floor |
| 17411 | 18788 | apar | Jūrmala Dzintaru pr. 48 | 0.85 | same seller phone prefix; repost gap 8d; same floor |
| 19536 | 20403 | apar | Jēkabpils un rajons Jēkabpils  | 0.85 | same seller phone prefix; same floor |
| 19019 | 19112 | apar | Āgenskalns Ventspils 63c | 0.85 | same seller phone prefix; repost gap 15d; same floor |
| 18688 | 20403 | apar | Jēkabpils un rajons Jēkabpils  | 0.85 | same seller phone prefix; same floor |
| 18792 | 20403 | apar | Jēkabpils un rajons Jēkabpils  | 0.85 | same seller phone prefix; repost gap 21d; same floor |
| 16599 | 20319 | apar | Purvciems Ilukstes 54 | 0.83 | comment Jaccard 0.99; same seller phone prefix; repost gap 25d; same floor |
| 6352 | 18963 | apar | Imanta Kleistu 18 | 0.83 | comment Jaccard 0.81; same seller phone prefix; repost gap 20d; same floor |
| 19498 | 19501 | apar | Rēzekne un rajons Rezekne  | 0.80 | identical comment; repost gap 0d; same floor |
| 17587 | 19948 | apar | Purvciems Dzelzavas 25 | 0.80 | identical comment; repost gap 2d; same floor |
| 7147 | 20303 | apar | Teika Kaukaza 11 | 0.80 | comment Jaccard 0.98; same floor; coexisted 49d |
| 10537 | 20081 | apar | Dreiliņi Valtera 1 | 0.80 | comment Jaccard 0.95; same floor |
| 18555 | 18914 | apar | Centrs Strelnieku 4b | 0.80 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |
| 19297 | 19935 | apar | Vecrīga Pasta 6 | 0.80 | comment Jaccard 0.92; repost gap 11d; same floor |
| 20194 | 20461 | apar | Krāslava un rajons Kraslava  | 0.80 | comment Jaccard 0.84; repost gap 1d; same floor |
| 1824 | 19080 | apar | Centrs Elizabetes 22 | 0.80 | comment Jaccard 0.84; same seller phone prefix; same floor |
| 18536 | 18849 | apar | Centrs Brivibas 148 | 0.80 | comment sim 0.52; same seller phone prefix; same floor |
| 10263 | 19817 | apar | Centrs Vashingtona pl. 2 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 39d |
| 10251 | 20585 | apar | Centrs Bruninieku 20 | 0.78 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 10329 | 19558 | apar | Centrs Blaumana 20 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 56d |
| 1891 | 19002 | apar | Centrs Vagonu 22 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 19134 | 18101 | apar | Centrs Matisa 27 | 0.78 | identical comment; same seller phone prefix; repost gap 3d; FLOOR CONFLICT |
| 5982 | 18557 | apar | Centrs Dzirnavu 27 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 19224 | 17439 | apar | Centrs Matisa 27 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 10540 | 20274 | apar | Dreiliņi Valtera 1b | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 12652 | 19902 | apar | Čiekurkalns Chiekurkalna 7. cr..  | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 902 | 19109 | apar | Ķengarags Kengaraga 10 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 13719 | 19369 | apar | Mežciems Eizenshteina 47 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 13719 | 19370 | apar | Mežciems Eizenshteina 47 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 16060 | 19706 | apar | Pļavnieki Salnas 21 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 12229 | 12230 | apar | Sigulda Cēsu 7 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 19280 | 18303 | apar | Iļģuciems Spilves 27 | 0.78 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 16072 | 20086 | apar | Valka un rajons Seda  | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 9868 | 19576 | apar | Ādažu nov. Ūbeļu 9 | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 9866 | 19575 | apar | Ādažu nov. Ūbeļu 9a | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 19312 | 18304 | apar | Iļģuciems Spilves 29 | 0.78 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 19314 | 18305 | apar | Iļģuciems Spilves 29 | 0.78 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 11635 | 19409 | apar | Mežciems Kaivas 48b | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 65d |
| 19431 | 12063 | apar | Purvciems Brantkalna 1a | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 19431 | 20075 | apar | Purvciems Brantkalna 1a | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 12063 | 20075 | apar | Purvciems Brantkalna 1a | 0.78 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 13718 | 19349 | apar | Mežciems Eizenshteina 47 | 0.78 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 20178 | 20179 | apar | Centrs Brivibas 68 | 0.78 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 18732 | 18735 | apar | Ziepniekkalns Graudu 8 | 0.78 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 15379 | 20487 | apar | Ventspils Talsu 3a | 0.78 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT; coexisted 21d |
| 7147 | 19494 | apar | Teika Kaukaza 11 | 0.78 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 1178 | 18944 | apar | Mārupes pag. Malduguņu 6 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 19d |
| 1178 | 19041 | apar | Mārupes pag. Malduguņu 6 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 32d |
| 1178 | 19097 | apar | Mārupes pag. Malduguņu 6 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 5982 | 18591 | apar | Centrs Dzirnavu 27 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 5982 | 18676 | apar | Centrs Dzirnavu 27 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 5982 | 18744 | apar | Centrs Dzirnavu 27 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 352 | 19015 | apar | Centrs Terbatas 72 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 10017 | 20565 | apar | Jūrmala Dzelzceļa 3a | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 1594 | 19124 | apar | Teika Kaukaza 11 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 1204 | 19125 | apar | Mežciems Eizenshteina 47 | 0.78 | comment Jaccard 0.98; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 149 | 18759 | apar | Centrs Terbatas 72 | 0.78 | comment Jaccard 0.98; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 352 | 18828 | apar | Centrs Terbatas 72 | 0.78 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 11634 | 20621 | apar | Mežciems Kaivas 48b | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 352 | 19016 | apar | Centrs Terbatas 72 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 15518 | 19655 | apar | Centrs Lachplesha 36 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 19385 | 19386 | apar | Iļģuciems Spilves 29 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 10333 | 19573 | apar | Centrs Brivibas 91 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 64d |
| 10333 | 19574 | apar | Centrs Brivibas 91 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 64d |
| 10333 | 20191 | apar | Centrs Brivibas 91 | 0.78 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 37d |
| 17716 | 19361 | apar | Centrs G. Kluca 10 | 0.78 | comment Jaccard 0.96; same seller phone prefix; repost gap 1d; FLOOR CONFLICT |
| 318 | 18956 | apar | Centrs Brivibas 106a | 0.78 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 47d |
| 11242 | 19253 | apar | Latgales priekšpilsēta Jekabpils 4 | 0.78 | comment Jaccard 0.95; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 8824 | 18548 | apar | Centrs Sadovnikova 31 | 0.78 | comment Jaccard 0.95; same seller phone prefix; repost gap 10d; FLOOR CONFLICT |
| 12524 | 20661 | apar | Vecrīga Pasta 6 | 0.78 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 15d |
| 17652 | 19407 | apar | Āgenskalns Ranka d. 30 | 0.78 | comment Jaccard 0.95; same seller phone prefix; repost gap 1d; FLOOR CONFLICT |
| 3790 | 18710 | apar | Centrs Avotu 11 | 0.78 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT |
| 12524 | 19972 | apar | Vecrīga Pasta 6 | 0.78 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT |
| 9917 | 20097 | apar | Āgenskalns Sabiles 15b | 0.78 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 42d |
| 13914 | 20285 | apar | Stopiņu nov. Rīgas 14 | 0.78 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 22d |
| 15384 | 15373 | apar | Ventspils Talsu 3a | 0.78 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 21d |
| 17654 | 19411 | apar | Āgenskalns Ranka d. 30 | 0.78 | comment Jaccard 0.93; same seller phone prefix; repost gap 1d; FLOOR CONFLICT |
| 10789 | 19437 | apar | Imanta Akaciju 2f | 0.78 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 1204 | 19126 | apar | Mežciems Eizenshteina 47 | 0.78 | comment Jaccard 0.92; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 19863 | 19865 | apar | Vecrīga Pasta 6 | 0.78 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 12518 | 19934 | apar | Vecrīga Pasta 6 | 0.78 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT |
| 14759 | 20199 | apar | Centrs Dainas 10a | 0.78 | comment Jaccard 0.92; same seller phone prefix; repost gap 1d; FLOOR CONFLICT |
| 17654 | 19408 | apar | Āgenskalns Ranka d. 30 | 0.78 | comment Jaccard 0.92; same seller phone prefix; repost gap 1d; FLOOR CONFLICT |
| 19408 | 19411 | apar | Āgenskalns Ranka d. 30 | 0.78 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT |
| 1891 | 19020 | apar | Centrs Vagonu 22 | 0.78 | comment Jaccard 0.91; same seller phone prefix; FLOOR CONFLICT |
| 8830 | 18599 | apar | Centrs Pernavas 41 | 0.78 | comment Jaccard 0.91; same seller phone prefix; repost gap 10d; FLOOR CONFLICT |
| 11832 | 19562 | apar | Pļavnieki Dravnieku 3 | 0.78 | comment Jaccard 0.91; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 1179 | 18945 | apar | Mārupes pag. Malduguņu 6 | 0.78 | comment Jaccard 0.89; same seller phone prefix; repost gap 28d; FLOOR CONFLICT |
| 19090 | 1575 | apar | Teika Kaukaza 11 | 0.78 | comment Jaccard 0.89; same seller phone prefix; FLOOR CONFLICT; coexisted 55d |
| 20086 | 20087 | apar | Valka un rajons Seda  | 0.78 | comment Jaccard 0.88; same seller phone prefix; FLOOR CONFLICT |
| 9710 | 18519 | apar | Mežaparks Kokneses pr. 36 | 0.78 | comment Jaccard 0.88; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 848 | 19006 | apar | Kauguri Lauku 35 | 0.78 | comment Jaccard 0.87; same seller phone prefix; repost gap 6d; FLOOR CONFLICT |
| 10318 | 19441 | apar | Centrs Stabu 59 | 0.78 | comment Jaccard 0.87; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 14512 | 19709 | apar | Centrs Lachplesha 36 | 0.78 | comment Jaccard 0.87; same seller phone prefix; FLOOR CONFLICT |
| 2491 | 18689 | apar | Centrs Brivibas 73 | 0.78 | comment Jaccard 0.86; same seller phone prefix; same floor |
| 19003 | 19020 | apar | Centrs Vagonu 22 | 0.78 | comment Jaccard 0.85; same seller phone prefix; repost gap 6d; FLOOR CONFLICT |
| 6245 | 18757 | apar | Centrs Avotu 75 | 0.78 | comment Jaccard 0.85; same seller phone prefix; repost gap 3d; FLOOR CONFLICT |
| 10791 | 19438 | apar | Imanta Akaciju 2f | 0.78 | comment Jaccard 0.84; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 19442 | 19443 | apar | Centrs Stabu 59 | 0.78 | comment Jaccard 0.84; same seller phone prefix; FLOOR CONFLICT; coexisted 42d |
| 13167 | 19582 | apar | Centrs Bruninieku 20 | 0.78 | comment Jaccard 0.83; same seller phone prefix; FLOOR CONFLICT; coexisted 36d |
| 10202 | 19601 | apar | Centrs Skolas 17 | 0.78 | comment Jaccard 0.82; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 19191 | 14138 | apar | Centrs Akas 4 | 0.78 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT |
| 12959 | 19610 | apar | Centrs Brivibas 138 | 0.78 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT; coexisted 62d |
| 9899 | 19791 | apar | Āgenskalns Sabiles 15b | 0.78 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT; coexisted 62d |
| 1754 | 19094 | apar | Ziepniekkalns Graudu 8 | 0.78 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT; coexisted 47d |
| 9899 | 19713 | apar | Āgenskalns Sabiles 15b | 0.78 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT; coexisted 62d |
| 10318 | 19442 | apar | Centrs Stabu 59 | 0.78 | comment Jaccard 0.80; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 10651 | 20220 | apar | Grīziņkalns Avotu 66a | 0.75 | identical comment; same floor |
| 5649 | 5650 | hous | Saulkrasti Mazā Neibādes 4 | 0.75 | comment Jaccard 1.00; repost gap 20d; same floors+land |
| 3877 | 18694 | apar | Āgenskalns M. Nometnu 67 | 0.75 | comment Jaccard 0.89; same seller phone prefix; FLOOR CONFLICT |
| 19297 | 19972 | apar | Vecrīga Pasta 6 | 0.75 | comment Jaccard 0.86; same seller phone prefix; same floor |
| 3999 | 18969 | apar | Jugla Veldres 20 | 0.75 | comment Jaccard 0.84; same floor |
| 18551 | 18791 | apar | Centrs Valmieras 13 | 0.75 | comment Jaccard 0.80; same seller phone prefix; repost gap 27d; same floor |
| 18551 | 18818 | apar | Centrs Valmieras 13 | 0.75 | comment Jaccard 0.80; same seller phone prefix; repost gap 28d; same floor |
| 5022 | 18820 | apar | Jūrmala Lauku 35 | 0.73 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 10334 | 20539 | apar | Centrs Bruninieku 20 | 0.73 | comment Jaccard 0.94; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 18604 | 20143 | apar | Teika Kaukaza 11 | 0.73 | same ad_id linked to both; comment sim 0.56; same seller phone prefix; repost gap 9d; FLOOR CONFLICT |
| 10224 | 19540 | apar | Centrs Lachplesha 36 | 0.70 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 64d |
| 15518 | 19564 | apar | Centrs Lachplesha 36 | 0.70 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 13910 | 20475 | apar | Tukums un rajons Smārdes pag.  | 0.70 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 52d |
| 16784 | 20270 | apar | Liepāja Vītolu 7/11 | 0.70 | identical comment; repost gap 20d; same floor |
| 19369 | 19370 | apar | Mežciems Eizenshteina 47 | 0.70 | identical comment; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 1449 | 19118 | apar | Salaspils Skolas 10 | 0.70 | identical comment; repost gap 0d; same floor |
| 14483 | 20014 | apar | Ziepniekkalns Malu 18 | 0.70 | identical comment; same seller phone prefix; FLOOR CONFLICT |
| 20070 | 20230 | apar | Centrs Gertrudes 56 | 0.70 | identical comment; same seller phone prefix; repost gap 7d; FLOOR CONFLICT |
| 19279 | 18301 | apar | Iļģuciems Spilves 27 | 0.70 | identical comment; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 4446 | 5649 | hous | Saulkrasti Mazā Neibādes 4 | 0.70 | comment Jaccard 1.00 |
| 11978 | 20181 | apar | Purvciems Nicgales 21 | 0.70 | comment Jaccard 0.99; repost gap 30d; same floor |
| 12064 | 20074 | apar | Purvciems Brantkalna 1a | 0.70 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 16308 | 19555 | apar | Centrs Brivibas 190 | 0.70 | comment Jaccard 0.98; same seller phone prefix; FLOOR CONFLICT |
| 991 | 18974 | apar | Latgales priekšpilsēta Vilanu 7 | 0.70 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT; coexisted 24d |
| 11634 | 19783 | apar | Mežciems Kaivas 48b | 0.70 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT; coexisted 60d |
| 8831 | 18625 | apar | Centrs Pernavas 41 | 0.70 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT |
| 10111 | 20252 | apar | Bieriņi Ives 3 | 0.70 | comment Jaccard 0.97; same seller phone prefix; FLOOR CONFLICT; coexisted 39d |
| 2245 | 18967 | apar | Sarkandaugava Hapsalas 12 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 3781 | 18759 | apar | Centrs Terbatas 72 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 19015 | 19016 | apar | Centrs Terbatas 72 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 7419 | 18750 | apar | Jūrmala Mežaparka pr. 1 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT |
| 12538 | 19866 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 12524 | 12519 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.96; same seller phone prefix; FLOOR CONFLICT; coexisted 79d |
| 19157 | 19159 | apar | Latgales priekšpilsēta Latgales 146 | 0.70 | comment Jaccard 0.95; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 19710 | 20400 | apar | Liepāja Tērauda 11 | 0.70 | comment Jaccard 0.95; same floor |
| 12520 | 19297 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.95; repost gap 28d; same floor |
| 12524 | 19974 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 854 | 19052 | apar | Mangaļi Ezera 18 | 0.70 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 31d |
| 19359 | 19473 | apar | Centrs Zvaigzhnu 21 | 0.70 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT |
| 12519 | 19935 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 11840 | 19412 | apar | Pļavnieki Dravnieku 3 K-3  | 0.70 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 1631 | 19122 | apar | Torņakalns Apshu 4 | 0.70 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT |
| 19 | 19095 | apar | Āgenskalns Lielirbes 15 | 0.70 | comment Jaccard 0.94; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 14299 | 19739 | apar | Pļavnieki Kupricu 3b | 0.70 | comment Jaccard 0.94; same seller phone prefix; FLOOR CONFLICT; coexisted 44d |
| 4365 | 19034 | apar | Jēkabpils un rajons Jēkabpils  | 0.70 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT; coexisted 20d |
| 19213 | 9903 | apar | Āgenskalns Ranka d. 34 | 0.70 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT; coexisted 76d |
| 19864 | 19866 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT; coexisted 51d |
| 352 | 19067 | apar | Centrs Terbatas 72 | 0.70 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |
| 19125 | 19126 | apar | Mežciems Eizenshteina 47 | 0.70 | comment Jaccard 0.91; same seller phone prefix; FLOOR CONFLICT; coexisted 47d |
| 5757 | 18959 | apar | Centrs Cesu 9 | 0.70 | comment Jaccard 0.90; same seller phone prefix; repost gap 10d; FLOOR CONFLICT |
| 19738 | 20550 | apar | Latgales priekšpilsēta Katolu 9 | 0.70 | comment Jaccard 0.89; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 19297 | 19943 | apar | Vecrīga Pasta 6 | 0.70 | comment Jaccard 0.89; same seller phone prefix; repost gap 11d; FLOOR CONFLICT |
| 18507 | 21020 | apar | Sigulda Čakstes 11 | 0.70 | comment Jaccard 0.89; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 13540 | 19953 | apar | Ķīpsala Zvejnieku 34 | 0.70 | comment Jaccard 0.87; same seller phone prefix; FLOOR CONFLICT; coexisted 31d |
| 10210 | 20040 | apar | Centrs Artilerijas 11 | 0.70 | comment Jaccard 0.87; same seller phone prefix; FLOOR CONFLICT |
| 1891 | 19003 | apar | Centrs Vagonu 22 | 0.70 | comment Jaccard 0.86; same seller phone prefix; FLOOR CONFLICT |
| 16321 | 20027 | apar | Berģi Kaktusu 6 | 0.70 | comment Jaccard 0.85; same seller phone prefix; repost gap 5d; FLOOR CONFLICT |
| 10550 | 10564 | apar | Dubulti Pils 5 | 0.70 | comment Jaccard 0.83; same seller phone prefix; FLOOR CONFLICT; coexisted 55d |
| 19441 | 19442 | apar | Centrs Stabu 59 | 0.70 | comment Jaccard 0.82; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 17091 | 19589 | apar | Centrs Bruninieku 41 | 0.70 | comment Jaccard 0.81; same seller phone prefix; repost gap 4d; FLOOR CONFLICT |
| 1483 | 19076 | apar | Šampēteris-Pleskodāle Lielirbes 15 | 0.70 | comment Jaccard 0.80; same seller phone prefix; repost gap 0d; FLOOR CONFLICT |
| 1752 | 19000 | apar | Ziepniekkalns Skaistkalnes 17 | 0.68 | identical comment; same seller phone prefix; repost gap 22d; FLOOR CONFLICT |
| 15770 | 20443 | apar | Torņakalns Jelgavas 65 | 0.68 | comment Jaccard 0.99; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 8476 | 18521 | apar | Ķengarags Aviacijas 2e | 0.68 | comment Jaccard 0.99; same seller phone prefix; repost gap 17d; FLOOR CONFLICT |
| 16309 | 19554 | apar | Centrs Brivibas 190 | 0.68 | comment Jaccard 0.98; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 19164 | 12518 | apar | Vecrīga Pasta 6 | 0.68 | comment Jaccard 0.95; same seller phone prefix; repost gap 28d; FLOOR CONFLICT |
| 15702 | 19483 | apar | Centrs Brivibas 201 | 0.68 | comment Jaccard 0.94; same seller phone prefix; repost gap 30d; FLOOR CONFLICT |
| 20307 | 20613 | apar | Centrs Chaka 133 | 0.68 | comment Jaccard 0.92; same seller phone prefix; repost gap 21d; FLOOR CONFLICT |
| 3782 | 18657 | apar | Centrs Avotu 11 | 0.68 | comment Jaccard 0.91; same seller phone prefix; FLOOR CONFLICT |
| 1698 | 18863 | apar | Vecrīga Vecpilsetas 12 | 0.68 | comment Jaccard 0.90; same seller phone prefix; FLOOR CONFLICT |
| 2118 | 18826 | apar | Centrs Brivibas 108b | 0.68 | comment Jaccard 0.88; same seller phone prefix; FLOOR CONFLICT; coexisted 36d |
| 3680 | 18585 | apar | Teika Brivibas g. 312 | 0.68 | comment Jaccard 0.86; same seller phone prefix; repost gap 22d; FLOOR CONFLICT |
| 19158 | 10450 | apar | Centrs Zvaigzhnu 21 | 0.68 | comment Jaccard 0.81; same seller phone prefix; repost gap 29d; FLOOR CONFLICT |
| 10536 | 20274 | apar | Dreiliņi Valtera 1b | 0.65 | identical comment; FLOOR CONFLICT; coexisted 51d |
| 207 | 4970 | hous | Daugmales pag. Jaunāraji  | 0.65 | comment Jaccard 1.00; repost gap 9d |
| 207 | 4983 | hous | Daugmales pag. Jaunāraji  | 0.65 | comment Jaccard 1.00; repost gap 9d |
| 461 | 4974 | hous | Kundziņsala Kundzinsalas 7. cr..  | 0.65 | same ad_id linked to both; comment Jaccard 1.00 |
| 3390 | 4995 | hous | Mārupes pag. Rītausmas 1 | 0.65 | comment Jaccard 1.00; repost gap 0d |
| 764 | 4973 | hous | Saulkrasti Kalnu 6a | 0.65 | comment Jaccard 1.00 |
| 968 | 4972 | hous | Valteri Lazdu 6 | 0.65 | comment Jaccard 1.00 |
| 968 | 4991 | hous | Valteri Lazdu 6 | 0.65 | comment Jaccard 1.00 |
| 2567 | 5652 | hous | Dārzciems Karsavas 33 | 0.65 | comment Jaccard 1.00; repost gap 12d |
| 10541 | 10537 | apar | Dreiliņi Valtera 1 | 0.65 | comment Jaccard 0.95; FLOOR CONFLICT; coexisted 35d |
| 10537 | 20084 | apar | Dreiliņi Valtera 1 | 0.65 | comment Jaccard 0.95; FLOOR CONFLICT; coexisted 35d |
| 10537 | 20624 | apar | Dreiliņi Valtera 1 | 0.65 | comment Jaccard 0.95; FLOOR CONFLICT |
| 12519 | 19974 | apar | Vecrīga Pasta 6 | 0.65 | comment Jaccard 0.94; FLOOR CONFLICT; coexisted 67d |
| 12519 | 20661 | apar | Vecrīga Pasta 6 | 0.65 | comment Jaccard 0.90; FLOOR CONFLICT; coexisted 15d |
| 12835 | 20098 | apar | Centrs Alauksta 7 | 0.65 | comment Jaccard 0.89; same seller phone prefix; FLOOR CONFLICT; coexisted 20d |
| 12519 | 19972 | apar | Vecrīga Pasta 6 | 0.65 | comment Jaccard 0.88; FLOOR CONFLICT |
| 12525 | 14648 | apar | Vecrīga Pasta 6 | 0.65 | comment Jaccard 0.84; FLOOR CONFLICT; coexisted 40d |
| 10109 | 9581 | apar | Bieriņi Kantora 10 | 0.65 | comment Jaccard 0.84; FLOOR CONFLICT; coexisted 39d |
| 19244 | 13782 | apar | Pļavnieki Jasmuizhas 18 | 0.65 | comment Jaccard 0.83; same floor |
| 5571 | 5653 | hous | Liepāja Brīvības 103c | 0.65 | comment Jaccard 0.82; repost gap 0d |
| 14696 | 19465 | apar | Aizkraukle un rajons Neretas pag.  | 0.65 | comment Jaccard 0.81; FLOOR CONFLICT |
| 2525 | 18874 | apar | Centrs Valdemara 61 | 0.65 | comment Jaccard 0.81; same seller phone prefix; FLOOR CONFLICT; coexisted 29d |
| 19279 | 18298 | apar | Iļģuciems Spilves 27 | 0.65 | comment Jaccard 0.80; repost gap 0d; FLOOR CONFLICT |
| 19246 | 19280 | apar | Iļģuciems Spilves 27 | 0.65 | comment Jaccard 0.80; repost gap 0d; FLOOR CONFLICT |
| 2390 | 19476 | apar | Centrs Artilerijas 19 | 0.65 | same ad_id linked to both; repost gap 13d; same floor |
| 7147 | 20711 | apar | Teika Kaukaza 11 | 0.65 | same ad_id linked to both; same floor |
| 4827 | 18804 | apar | Āgenskalns Zemaishu 15 | 0.63 | identical comment; same seller phone prefix; repost gap 18d; FLOOR CONFLICT |
| 6550 | 21006 | apar | Vecrīga Jana 3 | 0.63 | comment Jaccard 0.99; same seller phone prefix; FLOOR CONFLICT |
| 18304 | 19386 | apar | Iļģuciems Spilves 29 | 0.63 | comment Jaccard 0.83; repost gap 13d; same floor |
| 19935 | 19972 | apar | Vecrīga Pasta 6 | 0.63 | comment Jaccard 0.82; same floor |
| 19134 | 17426 | apar | Centrs Matisa 27 | 0.60 | identical comment; same seller phone prefix; repost gap 21d; FLOOR CONFLICT |
| 2415 | 2414 | hous | Carnikavas nov. Dzirnupes 3e | 0.60 | comment Jaccard 1.00; same floors+land |
| 4119 | 5646 | hous | Stopiņu nov. Mežrozīšu 2 | 0.60 | comment Jaccard 1.00 |
| 10450 | 19654 | apar | Centrs Zvaigzhnu 21 | 0.60 | comment Jaccard 0.98; FLOOR CONFLICT; coexisted 34d |
| 205 | 19024 | apar | Centrs Pulkv. Briezha 3 | 0.60 | comment Jaccard 0.97; same seller phone prefix; repost gap 15d; FLOOR CONFLICT |
| 18828 | 19016 | apar | Centrs Terbatas 72 | 0.60 | comment Jaccard 0.95; same seller phone prefix; FLOOR CONFLICT |
| 349 | 18721 | apar | Centrs Cesu 9 | 0.60 | comment Jaccard 0.94; same seller phone prefix; repost gap 15d; same floor |
| 3120 | 18821 | apar | Teika Kurshu 25 | 0.60 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT |
| 410 | 18705 | apar | Centrs Stabu 70 | 0.60 | comment Jaccard 0.92; same seller phone prefix; FLOOR CONFLICT |
| 10318 | 19443 | apar | Centrs Stabu 59 | 0.60 | comment Jaccard 0.88; same seller phone prefix; repost gap 21d; FLOOR CONFLICT |
| 19297 | 20661 | apar | Vecrīga Pasta 6 | 0.60 | comment Jaccard 0.85; same seller phone prefix; FLOOR CONFLICT |
| 2906 | 21011 | apar | Mārupes pag. Malduguņu 6 | 0.60 | comment Jaccard 0.85; same seller phone prefix; FLOOR CONFLICT |
| 331 | 4971 | hous | Imanta Cerinu 20 | 0.58 | comment Jaccard 1.00; repost gap 6d |
| 3448 | 4987 | hous | Mārupes pag. Samtu 1 | 0.58 | comment Jaccard 1.00; repost gap 3d |
| 2389 | 2394 | hous | Bulduri Meža prospekts 61 | 0.58 | comment Jaccard 1.00 |
| 330 | 4969 | hous | Imanta Cerinu 20 | 0.55 | comment Jaccard 1.00; repost gap 20d |
| 2028 | 4995 | hous | Mārupes pag. Rītausmas 1 | 0.55 | comment Jaccard 1.00 |
| 884 | 4968 | hous | Suntažu pag. SuntažiStacija  | 0.55 | comment Jaccard 1.00; repost gap 21d |
| 884 | 4978 | hous | Suntažu pag. SuntažiStacija  | 0.55 | comment Jaccard 1.00; repost gap 21d |
| 4325 | 4981 | hous | Zolitūde Imantas 18. l. 5 | 0.55 | comment Jaccard 1.00; repost gap 20d |
| 2301 | 18549 | apar | Āgenskalns Ranka d. 31 | 0.55 | comment Jaccard 0.94; FLOOR CONFLICT |
| 67 | 19021 | apar | Āgenskalns Valentina 16 | 0.55 | comment Jaccard 0.91; repost gap 15d; FLOOR CONFLICT |
| 19297 | 20271 | apar | Vecrīga Pasta 6 | 0.55 | comment Jaccard 0.91; repost gap 28d; FLOOR CONFLICT |
| 10367 | 20045 | apar | Centrs Terbatas 78a | 0.55 | comment Jaccard 0.88; FLOOR CONFLICT |
| 12520 | 19972 | apar | Vecrīga Pasta 6 | 0.55 | comment Jaccard 0.86; same floor |
| 4516 | 4513 | apar | Rēzekne un rajons Rezekne  | 0.55 | comment Jaccard 0.82; same seller phone prefix; FLOOR CONFLICT; coexisted 20d |
| 4485 | 18655 | apar | Neretas pag. Raiņa 19 | 0.55 | comment Jaccard 0.81; FLOOR CONFLICT |
| 6568 | 20599 | apar | Ziepniekkalns Tadaiku 9a | 0.55 | same ad_id linked to both; comment sim 0.80; same floor |
| 349 | 18959 | apar | Centrs Cesu 9 | 0.53 | comment Jaccard 0.95; same seller phone prefix; repost gap 26d; FLOOR CONFLICT |
| 10200 | 19359 | apar | Centrs Zvaigzhnu 21 | 0.50 | comment Jaccard 0.97; repost gap 17d; FLOOR CONFLICT |
| 4149 | 18615 | apar | Aizkraukle un rajons Skrīveru pag.  | 0.50 | comment Jaccard 0.92; FLOOR CONFLICT |
| 18240 | 19714 | apar | Centrs Bruninieku 41 | 0.50 | comment Jaccard 0.84; same seller phone prefix; repost gap 27d; FLOOR CONFLICT |
| 350 | 19108 | apar | Centrs Matisa 18 | 0.48 | identical comment; repost gap 0d; FLOOR CONFLICT |
| 10536 | 10540 | apar | Dreiliņi Valtera 1b | 0.48 | identical comment; FLOOR CONFLICT; coexisted 63d |
| 2028 | 3390 | hous | Mārupes pag. Rītausmas 1 | 0.48 | comment Jaccard 1.00 |
| 19494 | 20303 | apar | Teika Kaukaza 11 | 0.48 | comment Jaccard 0.98; FLOOR CONFLICT; coexisted 49d |
| 10040 | 10120 | apar | Bieriņi Liepajas 37c | 0.48 | comment Jaccard 0.91; FLOOR CONFLICT; coexisted 65d |
| 16117 | 19446 | apar | Centrs Terbatas 78a | 0.48 | comment Jaccard 0.88; repost gap 27d; FLOOR CONFLICT |
| 19935 | 20661 | apar | Vecrīga Pasta 6 | 0.48 | comment Jaccard 0.81; FLOOR CONFLICT; coexisted 15d |
| 19246 | 18303 | apar | Iļģuciems Spilves 27 | 0.48 | comment Jaccard 0.80; repost gap 0d; FLOOR CONFLICT |
| 349 | 18587 | apar | Centrs Cesu 9 | 0.45 | comment Jaccard 0.93; same seller phone prefix; FLOOR CONFLICT |

### MEDIUM — 972 pairs (worth a manual look)

Breakdown:
- 0.6–0.8: 691
- 0.6–0.8 + floor conflict: 90
- 0.45–0.6 + floor conflict: 76
- ≥0.8 + floor conflict: 55
- ≥0.8 + floor conflict + coexisted: 30
- 0.45–0.6: 24
- 0.6–0.8 + coexisted: 5
- ≥0.8: 1

The ~30 strongest MEDIUM examples:

| Prop A | Prop B | Type | Address | Score | Evidence |
|---|---|---|---|---|---|
| 5022 | 18866 | apar | Jūrmala Lauku 35 | 0.80 | comment sim 0.79; same seller phone prefix; FLOOR CONFLICT |
| 12261 | 20165 | apar | Sigulda Institūta 1 | 0.80 | comment sim 0.78; same seller phone prefix; FLOOR CONFLICT; coexisted 30d |
| 6339 | 18815 | apar | Iļģuciems Bullu 20 | 0.80 | comment sim 0.78; same seller phone prefix; FLOOR CONFLICT |
| 12591 | 20185 | apar | Ziepniekkalns M. Sterstu 8 | 0.80 | comment sim 0.78; same seller phone prefix; FLOOR CONFLICT; coexisted 30d |
| 10868 | 19894 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.78; same seller phone prefix; FLOOR CONFLICT |
| 12317 | 19776 | apar | Talsi un rajons Talsi  | 0.80 | comment sim 0.76; same seller phone prefix; FLOOR CONFLICT |
| 10208 | 20024 | apar | Centrs Gertrudes 56 | 0.80 | comment sim 0.71; same seller phone prefix; FLOOR CONFLICT; coexisted 21d |
| 1527 | 20576 | apar | Sigulda Strēlnieku 11a | 0.80 | comment sim 0.71; same seller phone prefix; FLOOR CONFLICT |
| 16968 | 19538 | apar | Centrs Pulkv. Briezha 10 | 0.80 | comment sim 0.71; same seller phone prefix; FLOOR CONFLICT |
| 11859 | 19412 | apar | Pļavnieki Dravnieku 3 K-3  | 0.80 | comment sim 0.71; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 10871 | 19895 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.70; same seller phone prefix; FLOOR CONFLICT |
| 10871 | 19836 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.69; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 10871 | 19837 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.67; same seller phone prefix; FLOOR CONFLICT |
| 10868 | 20390 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.63; same seller phone prefix; FLOOR CONFLICT |
| 10868 | 20391 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.63; same seller phone prefix; FLOOR CONFLICT; coexisted 32d |
| 13257 | 20070 | apar | Centrs Gertrudes 56 | 0.80 | comment sim 0.61; same seller phone prefix; FLOOR CONFLICT |
| 15503 | 19517 | apar | Āgenskalns Trijadibas 1a | 0.80 | comment sim 0.61; same seller phone prefix; FLOOR CONFLICT |
| 4532 | 19012 | apar | Rēzekne un rajons Rezekne  | 0.80 | comment sim 0.59; same seller phone prefix; FLOOR CONFLICT; coexisted 20d |
| 10871 | 20036 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.57; same seller phone prefix; FLOOR CONFLICT; coexisted 67d |
| 10871 | 20691 | apar | Jelgava Pumpura 7 | 0.80 | comment sim 0.57; same seller phone prefix; FLOOR CONFLICT |
| 13005 | 19862 | apar | Āgenskalns Trijadibas 1a | 0.80 | comment sim 0.53; same seller phone prefix; FLOOR CONFLICT; coexisted 44d |
| 12322 | 20047 | apar | Teika Brivibas g. 201 | 0.80 | comment sim 0.51; same seller phone prefix; FLOOR CONFLICT |
| 9488 | 20123 | apar | Cēsis un rajons Cēsis  | 0.80 | comment sim 0.51; same seller phone prefix; FLOOR CONFLICT |
| 5022 | 18652 | apar | Jūrmala Lauku 35 | 0.80 | comment sim 0.50; same seller phone prefix; repost gap 13d; FLOOR CONFLICT |
| 10871 | 20553 | apar | Jelgava Pumpura 7 | 0.80 | same seller phone prefix; FLOOR CONFLICT |
| 10871 | 20552 | apar | Jelgava Pumpura 7 | 0.80 | same seller phone prefix; FLOOR CONFLICT |
| 398 | 18872 | apar | Centrs Lachplesha 111 | 0.80 | same seller phone prefix; FLOOR CONFLICT |
| 10092 | 20113 | apar | Bieriņi Liepajas 37c | 0.80 | same seller phone prefix; FLOOR CONFLICT; coexisted 42d |
| 10871 | 19754 | apar | Jelgava Pumpura 7 | 0.80 | same seller phone prefix; FLOOR CONFLICT |
| 2481 | 19982 | apar | Centrs Aluksnes 1 | 0.80 | same seller phone prefix; FLOOR CONFLICT |

### LOW — 3268 pairs (probably distinct units)

Reasons (a pair may have several):
- different floors: 1476
- score-only similarity, no corroboration: 1342
- price mismatch: 467
- coexisted >14d: 388

2998 of them are in the 0.45–0.6 band — mostly same-building neighbours (same rooms/size/floor/project) with no apt, seller, or comment evidence connecting them.

## 3. Unmatched ads

36 ads have best block-candidate score ≥0.30 (all exactly 0.35 — typically size≤1m² +project or similar partial signals).

| Verdict | Count |
|---|---|
| LIKELY_SAME | 6 |
| PLAUSIBLE | 4 |
| UNLIKELY | 26 |
| score <0.30 — correctly unmatched | 170 |

| Ad | Model | Street | Cand. prop | Evidence |
|---|---|---|---|---|
| tr_58139334 | AptForRent | Centrs Dzirnavu 27 | 18557 | comment sim 0.65, phone match, r3/60.0m² vs r3/60.0m² |
| tr_58138283 | AptForRent | Ķengarags Latgales 427 | 8972 | comment sim 0.9, phone match, r1/33.0m² vs r1/33.0m² |
| tr_58141076 | AptForRent | Latgales priekšpilsēta Vilanu 16 | 11293 | comment sim 0.84, phone match, r1/20.0m² vs r1/20.0m² |
| tr_58140025 | AptForRent | Teika Kastranes 1 K-2  | 9829 | comment sim 0.88, phone match, r1/16.0m² vs r1/16.0m² |
| tr_58140236 | AptForRent | Daugavpils Cietoksna 8 | 20943 | comment sim 0.71, phone match, r3/54.0m² vs r3/54.0m² |
| tr_58140110 | AptForRent | Jelgava Garozas 32 | 9026 | comment sim 0.95, phone match, r3/70.0m² vs r3/70.0m² |
| tr_58029375 | AptForRent | Pāvilosta Dzintaru 95 | 3596 | comment sim 0.56, phone match, r3/50.0m² vs r3/50.0m² |
| tr_58140094 | AptForSale | Centrs Ausekla 4 | 10309 | comment sim 0.61, phone match, r3/80.0m² vs r3/80.0m² |
| tr_58140703 | AptForSale | Dārzciems Zeltinu 11 | 17944 | comment sim 0.85, phone match, r3/65.0m² vs r3/65.0m² |
| tr_58140778 | AptForSale | Ādažu nov. Ūbeļu 5 | 9857 | comment sim 0.3, phone match, r4/94.0m² vs r4/94.0m² |

The 26 UNLIKELY: candidate shares only rooms/size and maybe floor/project — different comment text (sim <0.3), no phone match, no apt number. Correctly left unmatched, though some are probably new units in buildings that already have properties.

## 4. Systemic observations

1. **is_sale_misclassified is the dominant cross-deal driver**: ~91% of cross-deal pairs (585/641) involve a rent-table ad flagged as actually-for-sale. These rows create phantom "rental" property rows whose sale-table twin is linked elsewhere. Suggest: link misclassified rows to their sale twin's property directly (same link = same listing), or run matching across deals before creating a new property.
2. **Conflated properties**: 13910, 16071, 16072 each hold ads for 2–4 different apartments. Root cause: sale ads often lack apt_no, and same-rooms/same-size units in one building then survive every hard reject; seller+size+floor pushes past 0.8. Consider a hard reject on *coexisting* ads with differing comment apt numbers, or penalizing second-unit absorption.
3. **Apt_no is nearly absent** in this set: 1 shared apt match and 0 conflicts in 4,797 same-block pairs. The extraction patterns fire rarely — most ads simply never state the number. The blocker therefore cannot separate same-stairwell units; that is what the MEDIUM tier is made of.
4. **Score inflation via multi-ad summing**: merged pair scores reach 1.25 — scoring appears to accumulate contributions from several ads, so ≥0.8 is reachable through many weak signals rather than one strong one.
5. **Canonical floor is noisy**: 75/5,020 properties have internally inconsistent ad floors (best-ad pick). Floor conflicts were therefore treated as soft negatives, not hard rejects.
6. **House ads all have rooms=0** and no floor — matching relies on size/floors/land/comment only; several HIGH house pairs rest on identical comments.
7. **Seller phones are masked in the export** (`(+371)XX-XX-***`) — only 4-digit prefix matching was possible here; the matcher itself compares full numbers. 1,001 pairs share a prefix; treat as weak evidence.
8. **Temporal window is short** (Jul–Oct 2026, ~80 days): "coexistence" negatives are weak — a 30m² flat advertised continuously and reposted is expected; several repost-gap 0d pairs look like same-day delete/repost cycles.
9. **Data quirks**: tr_ ids match across categories because ss.com reuses the ad object id — same `ad_id` + same link = same listing, but its *attributes* can differ between the rent and sale rows (edited listings or per-category parsing: see ATTR_CONFLICT). post_date can be absent (house rows).