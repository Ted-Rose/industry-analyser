import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRentVsBuyRanked,
  type Kind,
  type RentVsBuyGroup,
  type RentVsBuyRankedRowOut,
} from '../api';
import { formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';
import { cx } from '../../shared/cx';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';
import Checkbox from '../../shared/ui/Checkbox';
import DataTable, { type Column } from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState, { Alert } from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import useErrorToast from '../useErrorToast';

const KINDS: { kind: Kind; label: string }[] = [
  { kind: 'apartment', label: 'Apartments' },
  { kind: 'house', label: 'Houses' },
];

/** Cell dimension alongside the region — drives the `group` URL
 *  param → the API's group_by ('type' default). */
const GROUPS: { group: RentVsBuyGroup; label: string }[] = [
  { group: 'type', label: 'By type' },
  { group: 'region', label: 'By region' },
  { group: 'rooms', label: 'By rooms' },
];

/** Header of the grouping column per group_by mode — 'type'
 *  keeps the kind-specific label (Project/House type), 'region'
 *  merges into 'All' cells, 'rooms' shows the bucket. */
function groupHeader(group: RentVsBuyGroup, kind: Kind): string {
  if (group === 'rooms') return 'Rooms';
  if (group === 'region') return 'Type';
  return kind === 'apartment' ? 'Project' : 'House type';
}

/** Rows under both thresholds on both ad sides are excluded by the
 *  API already (min_ads); rows that pass the gate but stay thin
 *  (<20 on either side) or compare unlike sizes are de-emphasized. */
const THIN_AD_COUNT = 20;
const TOP_HIGHLIGHT = 10;

function isThin(row: RentVsBuyRankedRowOut): boolean {
  return row.n_rent_ads < THIN_AD_COUNT || row.n_sale_ads < THIN_AD_COUNT;
}

function isFlagged(row: RentVsBuyRankedRowOut): boolean {
  return !row.size_comparable || isThin(row);
}

/**
 * Joined router-link strip — SegmentedControl's look, real Links
 * (plan §8.8: tests select them by the link role, so the radio
 * SegmentedControl is not an option here).
 */
function LinkStrip({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="inline-flex items-center gap-0.5 rounded-md
        border border-border bg-surface-2 p-0.5"
    >
      {children}
    </div>
  );
}

function StripLink({
  to,
  active,
  children,
}: {
  to: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      aria-current={active ? 'page' : undefined}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-sm px-3 py-1 ' +
          'text-sm font-medium transition-colors ' +
          'motion-safe:duration-120 ease-ia',
        active
          ? 'bg-surface text-fg shadow-xs'
          : 'text-fg-muted hover:text-fg',
      )}
    >
      {children}
    </Link>
  );
}

interface Draft {
  kind: Kind;
  group: RentVsBuyGroup;
  days: string;
  minAds: string;
  residual: boolean;
}

function parseGroup(param: string | null): RentVsBuyGroup {
  return param === 'region' || param === 'rooms' ? param : 'type';
}

/**
 * Ranked rent-vs-buy report — the API returns cells of (exact
 * region node x group_by dimension) pre-sorted ascending by
 * months_to_buyout: how many months of the median rent it takes
 * to buy the median unit outright. Filters live in the URL
 * (kind/days/min_ads/residual/group).
 */
export default function RentVsBuy() {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: (p) => {
        const kind =
          p.get('kind') === 'house' ? 'house' : 'apartment';
        return {
          kind,
          group: parseGroup(p.get('group')),
          // Inputs display the kind-aware effective default —
          // the API's 30-day default otherwise contradicts the
          // shown 90-day window for houses.
          days: p.get('days') ?? (kind === 'house' ? '90' : '30'),
          minAds: p.get('min_ads') ?? '15',
          residual: p.get('residual') === '1',
        };
      },
      toParams: (d) => {
        const next = new URLSearchParams();
        next.set('kind', d.kind);
        // 'type' is the API default — only non-default modes
        // ride the query string (additive param).
        if (d.group !== 'type') next.set('group', d.group);
        // Cleared inputs drop the param — the input and the
        // query then fall back to the kind-aware default
        // (an empty `days=` would bypass it).
        if (d.days) next.set('days', d.days);
        if (d.minAds) next.set('min_ads', d.minAds);
        if (d.residual) next.set('residual', '1');
        return next;
      },
    });

  // kind/group ride the same URL but change via the link strips,
  // not the form — read them from the applied params (draft copies
  // exist only so apply() can re-serialize them).
  const kind: Kind =
    searchParams.get('kind') === 'house' ? 'house' : 'apartment';
  const group = parseGroup(searchParams.get('group'));
  const params = {
    // Houses default to a 90-day window in the input but the API
    // default is 30 — send the kind-aware default so the query
    // matches what the input shows. Apartment's 30 is already
    // the API default — only non-default values ride the query.
    days:
      searchParams.get('days') ?? (kind === 'house' ? '90' : null),
    minAds: searchParams.get('min_ads'),
    includeResidual: searchParams.get('residual') === '1',
    group: group === 'type' ? null : group,
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'rent-vs-buy-ranked',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchRentVsBuyRanked(kind, params),
  });
  useErrorToast(isError, error, 'Failed to load ranking');

  const urls = kindUrls(kind);

  const kindUrl = (k: Kind) => {
    const next = new URLSearchParams(searchParams);
    next.set('kind', k);
    return `?${next}`;
  };

  const groupUrl = (g: RentVsBuyGroup) => {
    const next = new URLSearchParams(searchParams);
    if (g === 'type') {
      next.delete('group');
    } else {
      next.set('group', g);
    }
    const qs = next.toString();
    return qs ? `?${qs}` : '';
  };

  const activeCount =
    (searchParams.get('days') ? 1 : 0) +
    (searchParams.get('min_ads') ? 1 : 0) +
    (searchParams.get('residual') === '1' ? 1 : 0);

  return (
    <PageContainer width="page">
      <PageHeader
        back={{ to: '/', label: 'Classified Ads' }}
        title="Rent vs Buy — ranked"
        description={
          'Months of median rent needed to buy the median unit ' +
          'outright, per region x property type — lower means ' +
          'buying looks cheap relative to renting. Only cells ' +
          'with at least the minimum ad count on both sides are ' +
          'ranked.'
        }
        actions={
          // PageHeader's actions row is nowrap — the strips
          // (~490px combined) overflow at 360px, so they get
          // their own wrapping row inside it.
          <div className="flex flex-wrap items-center gap-2">
            <LinkStrip label="Kind">
              {KINDS.map((k) => (
                <StripLink
                  key={k.kind}
                  to={kindUrl(k.kind)}
                  active={kind === k.kind}
                >
                  {k.label}
                </StripLink>
              ))}
            </LinkStrip>
            <LinkStrip label="Grouping">
              {GROUPS.map((g) => (
                <StripLink
                  key={g.group}
                  to={groupUrl(g.group)}
                  active={group === g.group}
                >
                  {g.label}
                </StripLink>
              ))}
            </LinkStrip>
          </div>
        }
      />

      <FilterBar
        onSubmit={apply}
        onReset={() =>
          reset({
            kind,
            group,
            days: kind === 'house' ? '90' : '30',
            minAds: '15',
            residual: false,
          })
        }
        activeCount={activeCount}
        collapsible="mobile"
        className="mb-4"
      >
        <Field label="Window (days)" htmlFor="id_days">
          <Input
            type="number"
            id="id_days"
            min="1"
            max="365"
            value={draft.days}
            onChange={(e) =>
              setDraft((d) => ({ ...d, days: e.target.value }))
            }
          />
        </Field>
        <Field label="Min ads per side" htmlFor="id_min_ads">
          <Input
            type="number"
            id="id_min_ads"
            min="1"
            value={draft.minAds}
            onChange={(e) =>
              setDraft((d) => ({ ...d, minAds: e.target.value }))
            }
          />
        </Field>
        {/* items-end drops the checkbox level with the row's
            inputs (it carries no Field label row of its own). */}
        <div className="flex items-end">
          <Checkbox
            label="Include residual regions"
            checked={draft.residual}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                residual: e.target.checked,
              }))
            }
          />
        </div>
      </FilterBar>

      {isError && !data ? (
        <ErrorState
          title="Failed to load ranking"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <div className="space-y-6">
          <Card padding="none" className="overflow-hidden">
            <RankedTable
              rows={(data?.results ?? []).map((row, i) => ({
                row,
                rank: i + 1,
              }))}
              kind={kind}
              group={group}
              regionAds={urls.regionAds}
              loading={isPending}
              empty={
                <EmptyState
                  title={
                    'No cells pass the minimum ad count in ' +
                    'this window.'
                  }
                />
              }
              caption="Rent vs buy ranking"
            />
          </Card>
          {data && data.residual.length > 0 && (
            <section>
              <h2 className="mb-3 text-xl font-semibold text-fg">
                Residual regions (ads on parent-level or unset
                regions — not ranked)
              </h2>
              <Card padding="none" className="overflow-hidden">
                <RankedTable
                  rows={data.residual.map((row) => ({
                    row,
                    rank: null,
                  }))}
                  kind={kind}
                  group={group}
                  regionAds={urls.regionAds}
                  loading={false}
                  caption="Residual regions"
                />
              </Card>
            </section>
          )}
          {data &&
            data.n_residual_cells > 0 &&
            data.residual.length === 0 && (
              <p className="text-sm text-fg-muted">
                {data.n_residual_cells} more{' '}
                {data.n_residual_cells === 1
                  ? 'cell passes'
                  : 'cells pass'}{' '}
                the gate in residual regions — enable "Include
                residual regions" to see them.
              </p>
            )}
          {data && (
            <CaveatNote
              dateFrom={data.date_from}
              dateTo={data.date_to}
              minAds={data.min_ads}
            />
          )}
        </div>
      )}
    </PageContainer>
  );
}

interface RankedRow {
  row: RentVsBuyRankedRowOut;
  /** 1-based rank in the main table; null in the residual one. */
  rank: number | null;
}

function flagTitles(row: RentVsBuyRankedRowOut): string[] {
  const flags: string[] = [];
  if (!row.size_comparable) flags.push('size gap');
  if (isThin(row)) flags.push('thin data');
  return flags;
}

function RankedTable({
  rows,
  kind,
  group,
  regionAds,
  loading,
  empty,
  caption,
}: {
  rows: RankedRow[];
  kind: Kind;
  group: RentVsBuyGroup;
  regionAds: (regionId: number) => string;
  loading: boolean;
  empty?: ReactNode;
  caption: string;
}) {
  // 15 numeric columns where row comparison matters → the
  // scroll mobile mode with a pinned region column; secondary
  // per-m²/size/paired columns drop below md (plan §6.1).
  const columns: Column<RankedRow>[] = [
    {
      id: 'region',
      header: 'Region',
      cell: ({ row, rank }) => {
        const flags = flagTitles(row);
        return (
          <>
            {rank !== null && (
              <span className="mr-1 text-fg-subtle tabular-nums">
                {rank}.
              </span>
            )}
            {row.region ? (
              <Link
                to={regionAds(row.region.id)}
                className="font-medium text-fg
                  hover:text-accent-text"
              >
                {row.region_label}
              </Link>
            ) : (
              row.region_label
            )}
            {flags.length > 0 && (
              <span
                className="ml-1 text-warning"
                title={flags.join(', ')}
              >
                ⚠
              </span>
            )}
          </>
        );
      },
    },
    {
      id: 'group',
      header: groupHeader(group, kind),
      cell: ({ row }) => row.property_type,
    },
    {
      id: 'months',
      header: 'Months to buy',
      align: 'right',
      cell: ({ row }) => (
        <span className="font-medium">
          {formatFloat(row.months_to_buyout, 1)}
        </span>
      ),
    },
    {
      id: 'years',
      header: 'Years',
      align: 'right',
      cell: ({ row }) => formatFloat(row.years_to_buyout, 1),
    },
    {
      id: 'yield',
      header: 'Yield %',
      align: 'right',
      cell: ({ row }) => formatFloat(row.gross_yield_pct, 1),
    },
    {
      id: 'med_rent',
      header: 'Med rent €/mo',
      align: 'right',
      cell: ({ row }) => formatFloat(row.median_monthly_rent, 0),
    },
    {
      id: 'med_price',
      header: 'Med price €',
      align: 'right',
      cell: ({ row }) => formatFloat(row.median_total_price, 0),
    },
    {
      id: 'rent_sqm',
      header: 'Rent €/m²',
      align: 'right',
      hideBelow: 'md',
      cell: ({ row }) =>
        formatFloat(row.median_monthly_rent_per_sqm, 2),
    },
    {
      id: 'sale_sqm',
      header: 'Sale €/m²',
      align: 'right',
      hideBelow: 'md',
      cell: ({ row }) =>
        formatFloat(row.median_sale_price_per_sqm, 0),
    },
    {
      id: 'size_rent',
      header: 'Rent m²',
      align: 'right',
      hideBelow: 'md',
      cell: ({ row }) => formatFloat(row.median_size_rent, 0),
    },
    {
      id: 'size_sale',
      header: 'Sale m²',
      align: 'right',
      hideBelow: 'md',
      cell: ({ row }) => formatFloat(row.median_size_sale, 0),
    },
    {
      id: 'n_rent',
      header: 'n rent',
      align: 'right',
      cell: ({ row }) => row.n_rent_ads,
    },
    {
      id: 'n_sale',
      header: 'n sale',
      align: 'right',
      cell: ({ row }) => row.n_sale_ads,
    },
    {
      id: 'paired',
      header: 'Paired mo.',
      align: 'right',
      hideBelow: 'md',
      cell: ({ row }) => {
        // The paired median displays at ≥3 pairs; under 5 it's
        // thin — flag it † (title tooltip explains).
        const fewPairs =
          row.paired_months_to_buyout !== null &&
          row.n_paired_properties < 5;
        const pairTitle = row.n_paired_properties
          ? `${row.n_paired_properties} same-unit pairs` +
            (fewPairs ? ' — few pairs, indicative only' : '')
          : undefined;
        return (
          <span title={pairTitle}>
            {formatFloat(row.paired_months_to_buyout, 1)}
            {fewPairs && (
              <span title="few pairs — indicative only"> †</span>
            )}
          </span>
        );
      },
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      getRowKey={({ row }) =>
        `${row.region?.id ?? 'none'}-${row.property_type}`
      }
      loading={loading}
      empty={empty}
      caption={caption}
      mobile="scroll"
      stickyFirstColumn
      rowTone={({ row, rank }) =>
        !isFlagged(row) && rank !== null && rank <= TOP_HIGHLIGHT
          ? 'success'
          : isFlagged(row)
            ? 'muted'
            : null
      }
    />
  );
}

function CaveatNote({
  dateFrom,
  dateTo,
  minAds,
}: {
  dateFrom: string;
  dateTo: string;
  minAds: number;
}) {
  return (
    <Alert tone="info" title="Caveats:">
      Medians cover ads sighted between {dateFrom} and {dateTo};
      each cell needs ≥{minAds} ads on both sides to rank. The
      rent side counts whole-unit monthly lets only — day/week
      (short-stay) and room-share ads are excluded. Ads parked on
      parent-level regions are hidden unless "Include residual
      regions" is on. Rows marked ⚠ compare rent and sale units
      whose median sizes differ by more than 25%, or have fewer
      than {THIN_AD_COUNT} ads on a side — treat their
      months-to-buy as indicative only. The "Paired" column
      repeats the metric on properties carrying both a rent and a
      sale ad (shown at ≥3 pairs; † marks under 5 — indicative
      only). All figures use asking prices on both sides and are
      gross — vacancy, repairs, transaction costs (~2–3%) and
      income tax are not deducted; net yield is typically ~2–3pp
      lower, so the real buyout takes ~15–25% longer than shown.
    </Alert>
  );
}
