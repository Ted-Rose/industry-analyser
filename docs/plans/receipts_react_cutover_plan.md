# Receipts dashboard — React cutover plan

> **Status**: Plan. Ports the last plain-template page
> (`/receipts/`, a hand-styled `dashboard.html` spending report)
> onto the established React/Vite + django-ninja stack, following
> `docs/plans/react_frontend_migration/README.md` and the shipped
> `tv`/`dashboard` cutovers. No model changes → no migrations.

## Current state

- `receipts/views.py` — one function view `dashboard` (public, no
  auth) hard-coded to the `admin` user's receipts. All query logic
  lives here: `_parse_date`, `_default_range`, `_date_range`,
  `_months_covered`, `_by_category`, plus the aggregates
  (`Sum`/`Count`/`TruncMonth`) that must run on `base` — not the
  item-joined queryset (regression-tested).
- `receipts/urls.py` — `path('', views.dashboard,
  name='dashboard')`; `{% url 'receipts:dashboard' %}` is used by
  the template's "Last 12 months" preset.
- `receipts/templates/receipts/dashboard.html` — standalone page
  (no base template) with inline `<style>`: date-range form +
  presets, 3 summary cards, By-month / By-store / By-category
  (collapsible `<details>` + top-items) tables, and the
  all-receipts table with expandable per-receipt item rows.
- `receipts/tests.py` — `DashboardViewTests` asserts on rendered
  HTML and `resp.context`; imports `_default_range` from
  `receipts.views`.
- The dashboard SPA already links `/receipts/` in its top nav
  (`frontend/src/dashboard/routes/Dashboard.tsx`).

## Decisions

1. **Stays public.** Today's page has no login — use
   `react_app_public` for the shell and `auth=None` on the GET op
   (migration README rule: public stays public). The dataset
   remains hard-coded to the `admin` user; anonymous visitors see
   exactly what they see today.
2. **Slug**: entry `receipts`, mount `/receipts/`, API
   `/api/receipts/` — all identical, no `SPA_BASES`/`SPA_SUBPATHS`
   changes needed (`spa_url_for`'s mechanical `/api/receipts/x` →
   `/receipts/x` rewrite is already correct; all ops are GETs so
   401s never arise anyway).
3. **One fat GET** for the whole page — the template renders
   everything server-side in one pass; the API mirrors that
   (serverless `CONN_MAX_AGE=0` makes granular calls the risk).
4. **Param names kept**: `?date_from=&date_to=` in the page URL —
   same names the template's form used, so bookmarks keep
   filtering.
5. **Money as `float`** in ninja schemas — matches
   `classified_ads` conventions (Decimal coerces cleanly); the
   client formats with a `formatMoney` helper.
6. **Strangler stage skipped** — single-route app, direct cutover
   like `tv`.

## Work items

### 1. `receipts/api.py` (new) — ninja router

Move the view's helpers and logic verbatim (classified_ads moved
`_compute_*_region_stats` the same way):

- `ADMIN_USERNAME`, `UNCATEGORIZED`, `TOP_CATEGORY_ITEMS`,
  `_parse_date`, `_default_range`, `_date_range(request)` (or a
  `date_from`/`date_to` param pair — see below),
  `_months_covered`, `_by_category`.
- `router = Router()`; one op:
  `@router.get('/', auth=None, response=ReceiptsDashboardOut)`
  with `date_from: Optional[date] = None`,
  `date_to: Optional[date] = None` params. Invalid input: the old
  view silently fell back to defaults on bad strings — ninja 422s
  on unparseable dates, which is *stricter* but still correct
  (the SPA only sends well-formed dates; keep the
  `date_from > date_to` → defaults swap server-side).

Schemas (all `float` for money, `Optional` where the template
branches on empty):

- `ReceiptItemOut` — `raw_name: str`, `is_fee: bool`,
  `quantity: float`, `unit: str`, `unit_price: Optional[float]`,
  `discount: float`, `total: float`.
- `ReceiptRowOut` — `id: int`, `purchased_at: Optional[datetime]`,
  `store_name: Optional[str]` (None → "(unknown)" client-side),
  `document_number: str`, `total: Optional[float]`,
  `currency: str`, `parse_status_label: str`
  (`resolve_parse_status_label →
  obj.get_parse_status_display()`), `item_count: int` (annotated),
  `items: List[ReceiptItemOut]` (`resolve_items →
  list(obj.items.all())` — the queryset already
  `prefetch_related`s `items`).
- `TopItemOut` — `raw_name: str`, `item_count: int`,
  `total: float`.
- `CategoryOut` — `name: str`, `item_count: int`, `total: float`,
  `monthly_avg: float`, `top_items: List[TopItemOut]`.
- `MonthlyRowOut` — `month: datetime`, `receipt_count: int`,
  `total: float`.
- `StoreRowOut` — `store_name: Optional[str]`,
  `receipt_count: int`, `total: float`.
- `SummaryOut` — `total_spend: float`, `receipt_count: int`
  (coerce `None` → `0`/`0.00` server-side).
- `ReceiptsDashboardOut` — `owner_exists: bool`, `summary`,
  `item_count: int`, `months: int`, `date_from: date`,
  `date_to: date`, `last_month_from: date`,
  `last_month_to: date`, `monthly: List[MonthlyRowOut]`,
  `by_store: List[StoreRowOut]`,
  `categories: List[CategoryOut]`,
  `receipts: List[ReceiptRowOut]`.

The op body is the existing `dashboard` view minus `render()`:
resolve owner (`None` → `Receipt.objects.none()`,
`owner_exists=False`), apply the date range, run the same
aggregates on `base` (not the item-joined QS — keep the comment
explaining why), return the schema.

### 2. `receipts/urls.py` — SPA cutover

```python
react_app_receipts = partial(
    react_app_public, entry='receipts', title='Receipts')

urlpatterns = [
    path('', react_app_receipts, name='dashboard'),
    path('<path:subpath>', react_app_receipts),
]
```

Keep `app_name = 'receipts'` and the `dashboard` name —
`reverse('receipts:dashboard')` callers (template preset, tests)
keep resolving. No trailing slash on the catch-all.

### 3. `industry_analyser/urls.py` — mount the router

`from receipts.api import router as receipts_router` +
`api.add_router('/receipts/', receipts_router)` alongside the
other routers. Update the stale comment above the receipts
include ("has no SPA entry" → SPA cutover note).

### 4. Frontend `src/receipts/` entry

- `main.tsx` — copy `src/tv/main.tsx`, `basename="/receipts"`,
  `./receipts.css`.
- `App.tsx` — `Route path="/"` → `ReceiptsDashboard`;
  `path="*"` → `<Navigate to="/" replace />`.
- `api.ts` — `fetchReceiptsDashboard({dateFrom?, dateTo?})` →
  `apiGet<ReceiptsDashboardOut>` on `/api/receipts/`; send
  `date_from`/`date_to` only when they match `YYYY-MM-DD` (the
  `setDate` guard in `src/dashboard/api.ts`). Type aliases over
  generated `api-types.ts`.
- `format.ts` — `formatMoney(value, currency='EUR')`,
  `formatMonth(iso)`, `formatDateTime(iso)` — port the
  template's `{{ x }} €` / `F Y` / `Y-m-d H:i` renderings.
- `routes/ReceiptsDashboard.tsx` — 1:1 port of the template:
  h1, the `owner_exists === false` empty notice, range form
  (`useSearchParams` `date_from`/`date_to`, draft-state pattern
  from `dashboard/routes/Dashboard.tsx`), presets ("Last month"
  sets server-provided `last_month_from/to`, "Last 12 months"
  clears params), "Showing X–Y", summary cards, By-month /
  By-store / By-category tables with `<details>` collapsibles
  (top-items), and All-receipts with per-row `<details>` item
  tables (`is_fee` → "(fee)" suffix). `useQuery` keyed on the
  search-param string; `errorDetail` alert on failure like the
  dashboard route.
- `receipts.css` — port the template's `<style>` rules into the
  app css conventions used by `tv.css`/`dashboard.css` (class
  names may stay identical).
- `routes/ReceiptsDashboard.test.tsx` — RTL smoke test: mock
  `../api`, assert summary cards + a category + a receipt row
  render (mirror `VacancyList.test.tsx`/`Dashboard.test.tsx`).

### 5. Build wiring

- `frontend/vite.config.ts` — add
  `receipts: 'src/receipts/main.tsx'` to `rollupOptions.input`.
- `frontend/package.json` — add `receipts` to the `gen:types`
  loop.
- `python manage.py export_openapi_schema --output
  frontend/openapi.json` then `cd frontend && npm run gen:types`;
  commit both `openapi.json` and `src/receipts/api-types.ts`
  (CI drift-checks them).

### 6. Deletions

- `receipts/views.py` — delete (helpers moved to `api.py`;
  nothing else imports it — `tests.py` import is updated).
- `receipts/templates/receipts/dashboard.html` — delete (the
  template's "Last 12 months" link becomes a client-side param
  clear).

### 7. `receipts/tests.py` — port `DashboardViewTests`

Rename to `ReceiptsApiTests`; same fixtures. Hit
`'/api/receipts/'` with the same params; assert on JSON, not
`resp.context`:

- 200 + shape (store name, doc number, totals, item names
  present).
- admin-only filtering (`OTHER-DOC` absent).
- missing admin user → `owner_exists is False`, empty sections.
- aggregates-not-inflated-by-item-join regression (Sum over the
  joined QS bug — keep verbatim).
- date-range filtering, last-12-months default, `from > to` →
  defaults. (Invalid *strings* now 422 — adjust that one case.)
- category grouping: order, `monthly_avg`, `top_items`.
- GET `/receipts/` still 200s (now the shell — assert
  `spa_shell.html` template or `<div id="root">`), and
  `reverse('receipts:dashboard')` still resolves.
- Update `from receipts.views import _default_range` →
  `from receipts.api import _default_range`.

### 8. PWA cache bump

`fetcher/views.py` `PWA_CACHE_VERSION = 'v7'` → `'v8'`
(migration step: bump on every shipped frontend change).

## Verification

```bash
python manage.py check
DATABASE_URL=sqlite:///db.sqlite3 python manage.py test receipts
cd frontend && npm run typecheck && npm test && npm run build
python manage.py export_openapi_schema \
  --output frontend/openapi.json   # + npm run gen:types; no drift
```

Manual smoke (`./dev.sh`): `/receipts/` renders the SPA; the
date-range form, presets, category `<details>`, and receipt item
rows behave like the template page; `/receipts/anything` serves
the shell (client route lands on `/receipts/`); POST to
`/receipts/` 404s.

## Out of scope

Category/rule management UI, receipt detail page, sync triggers —
the template never had them; admin + management commands stay.
