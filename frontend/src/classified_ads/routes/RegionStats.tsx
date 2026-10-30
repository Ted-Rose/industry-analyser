import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionStats,
  type Kind,
  type RegionStatsRowOut,
} from '../api';
import { formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import { kindUrls } from '../urls';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';
import CheckboxList from '../../shared/ui/CheckboxList';
import DataTable, { type Column } from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState, { Alert } from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import Select from '../../shared/ui/Select';
import { LoadingState } from '../../shared/ui/Skeleton';
import useErrorToast from '../useErrorToast';

interface Draft {
  dateFrom: string;
  dateTo: string;
  dealType: string;
  regions: Set<string>;
}

/** The stats columns shared by RegionStats and
 *  RegionStatsChildren — replaces StatsResultsTable (plan §9.8).
 *  '—' for null averages via formatFloat, matching the old
 *  templates' floatformat fallbacks. */
export function statsColumns(
  renderName: (row: RegionStatsRowOut) => ReactNode,
): Column<RegionStatsRowOut>[] {
  return [
    { id: 'region', header: 'Region', cell: renderName },
    {
      id: 'total_ads',
      header: 'Total ads',
      align: 'right',
      cell: (row) => row.total_ads,
    },
    {
      id: 'total_properties',
      header: 'Properties',
      align: 'right',
      cell: (row) => row.total_properties,
    },
    {
      id: 'avg_sqm',
      header: 'Avg €/m²',
      align: 'right',
      cell: (row) => formatFloat(row.avg_price_per_sqm, 0),
    },
    {
      id: 'avg_size',
      header: 'Avg size m²',
      align: 'right',
      cell: (row) => formatFloat(row.avg_size, 1),
    },
    {
      id: 'avg_tracked',
      header: 'Avg day count ad is open',
      align: 'right',
      cell: (row) => formatFloat(row.avg_days_tracked, 1),
    },
    {
      id: 'avg_market',
      header: 'Avg days on market',
      align: 'right',
      cell: (row) => formatFloat(row.avg_days_on_market, 1),
    },
  ];
}

/**
 * React port of region_stats.html / house_region_stats.html —
 * date range + deal type + a checkbox list of parent regions;
 * results render only once at least one region is checked (the old
 * `{% if results is not None %}` gate). Filters live in the URL.
 */
export default function RegionStats({ kind }: { kind: Kind }) {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: (p) => ({
        dateFrom: p.get('date_from') ?? '',
        dateTo: p.get('date_to') ?? '',
        dealType: p.get('deal_type') ?? '',
        regions: new Set(p.getAll('regions')),
      }),
      toParams: (d) => {
        const next = new URLSearchParams();
        if (d.dateFrom) next.set('date_from', d.dateFrom);
        if (d.dateTo) next.set('date_to', d.dateTo);
        if (d.dealType) next.set('deal_type', d.dealType);
        [...d.regions].forEach((id) => next.append('regions', id));
        return next;
      },
    });
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    dealType: searchParams.get('deal_type'),
    regions: searchParams.getAll('regions'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'region-stats',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchRegionStats(kind, params),
  });
  useErrorToast(isError, error, 'Failed to load stats');

  const urls = kindUrls(kind);
  const activeCount =
    (params.dateFrom ? 1 : 0) +
    (params.dateTo ? 1 : 0) +
    (params.dealType ? 1 : 0) +
    params.regions.length;

  return (
    <PageContainer width="page">
      <PageHeader
        back={{ to: urls.config, label: 'Back to Region Configuration' }}
        title={`${
          kind === 'apartment' ? 'Apartment' : 'House'
        } Region Stats`}
      />

      <FilterBar
        onSubmit={apply}
        onReset={reset}
        activeCount={activeCount}
        collapsible="mobile"
        submitLabel="Fetch"
        className="mb-4"
      >
        <Field label="From" htmlFor="id_date_from">
          <Input
            type="date"
            id="id_date_from"
            value={draft.dateFrom}
            onChange={(e) =>
              setDraft((d) => ({ ...d, dateFrom: e.target.value }))
            }
          />
        </Field>
        <Field label="To" htmlFor="id_date_to">
          <Input
            type="date"
            id="id_date_to"
            value={draft.dateTo}
            onChange={(e) =>
              setDraft((d) => ({ ...d, dateTo: e.target.value }))
            }
          />
        </Field>
        <Field label="Deal type" htmlFor="id_deal_type">
          <Select
            id="id_deal_type"
            value={draft.dealType}
            onChange={(e) =>
              setDraft((d) => ({ ...d, dealType: e.target.value }))
            }
          >
            <option value="">All</option>
            <option value="RENT">Rent</option>
            <option value="SELL">Sell</option>
          </Select>
        </Field>
        <Field
          label="Parent regions"
          className="sm:col-span-2 lg:col-span-4"
        >
          <CheckboxList
            legend="Parent regions"
            options={(data?.parent_regions ?? []).map((region) => ({
              value: String(region.id),
              label: region.name,
            }))}
            value={[...draft.regions]}
            onChange={(next) =>
              setDraft((d) => ({ ...d, regions: new Set(next) }))
            }
          />
        </Field>
      </FilterBar>

      {isError && !data ? (
        <ErrorState
          title="Failed to load stats"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <LoadingState variant="table" />
      ) : (
        data &&
        data.results !== null && (
          <>
            <Card padding="none" className="overflow-hidden">
              <DataTable
                columns={statsColumns((row) => (
                  <Link
                    to={`${urls.statsChildren(row.region.id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`}
                    className="font-medium text-fg
                      hover:text-accent-text"
                  >
                    {row.region.name}
                  </Link>
                ))}
                rows={data.results}
                getRowKey={(row) => row.region.id}
                empty={<EmptyState title="No regions selected." />}
                caption="Region statistics"
                mobile="scroll"
              />
            </Card>
            {!data.deal_type && <NoDealTypeNote />}
          </>
        )
      )}
    </PageContainer>
  );
}

/** The note shown when no deal type is picked — verbatim copy from
 *  the templates, now an Alert (plan §9.8). */
export function NoDealTypeNote() {
  return (
    <Alert tone="info" title="Note:" className="mt-4">
      Average values (€/m², size, days tracked) are only calculated
      when a specific deal type (Rent or Sell) is selected. Please
      select a deal type from the filter above to see these
      statistics.
    </Alert>
  );
}
