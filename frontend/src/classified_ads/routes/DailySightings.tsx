import { useQuery } from '@tanstack/react-query';
import {
  fetchDailySightings,
  type DailySightingsRowOut,
} from '../api';
import { formatDateWithWeekday } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';
import DataTable, { type Column } from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import Select from '../../shared/ui/Select';
import { StatCard, StatGrid } from '../../shared/ui/StatCard';
import useErrorToast from '../useErrorToast';

interface Draft {
  dateFrom: string;
  dateTo: string;
  region: string;
  order: string;
}

/**
 * React port of daily_sightings_report.html — per-day sighting counts
 * for the four ad tables inside a date window, optionally restricted
 * to a region subtree (parent + sub-region <optgroup> select) and an
 * asc/desc order toggle. Filters live in the URL; the summary cards
 * are computed from daily_data (rounded to whole numbers, matching
 * the template's widthratio math).
 */
export default function DailySightings() {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: (p) => ({
        dateFrom: p.get('date_from') ?? '',
        dateTo: p.get('date_to') ?? '',
        region: p.get('region') ?? '',
        order: p.get('order') ?? 'desc',
      }),
      toParams: (d) => {
        const next = new URLSearchParams();
        if (d.dateFrom) next.set('date_from', d.dateFrom);
        if (d.dateTo) next.set('date_to', d.dateTo);
        if (d.region) next.set('region', d.region);
        if (d.order) next.set('order', d.order);
        return next;
      },
    });
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    order: searchParams.get('order'),
    region: searchParams.get('region'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'sightings',
      searchParams.toString(),
    ],
    queryFn: () => fetchDailySightings(params),
  });
  useErrorToast(isError, error, 'Failed to load the report');

  const daily = data?.daily_data ?? [];
  const dayCount = daily.length;
  const aptAvg = dayCount
    ? Math.round(
        daily.reduce((s, d) => s + d.apartment_total, 0) / dayCount,
      )
    : 0;
  const houseAvg = dayCount
    ? Math.round(
        daily.reduce((s, d) => s + d.house_total, 0) / dayCount,
      )
    : 0;
  const grandSum = daily.reduce((s, d) => s + d.grand_total, 0);

  const columns: Column<DailySightingsRowOut>[] = [
    {
      id: 'date',
      header: 'Date',
      cell: (day) => formatDateWithWeekday(day.date),
    },
    {
      id: 'apt_rent',
      header: 'Apt. Rent',
      align: 'right',
      cell: (day) => day.apartment_rent,
    },
    {
      id: 'apt_sale',
      header: 'Apt. Sale',
      align: 'right',
      cell: (day) => day.apartment_sale,
    },
    {
      id: 'apt_total',
      header: 'Apt. Total',
      align: 'right',
      cell: (day) => (
        <span className="font-semibold">{day.apartment_total}</span>
      ),
    },
    {
      id: 'house_rent',
      header: 'House Rent',
      align: 'right',
      cell: (day) => day.house_rent,
    },
    {
      id: 'house_sale',
      header: 'House Sale',
      align: 'right',
      cell: (day) => day.house_sale,
    },
    {
      id: 'house_total',
      header: 'House Total',
      align: 'right',
      cell: (day) => (
        <span className="font-semibold">{day.house_total}</span>
      ),
    },
    {
      id: 'grand_total',
      header: 'Grand Total',
      align: 'right',
      cell: (day) => (
        <span className="font-semibold">{day.grand_total}</span>
      ),
    },
  ];

  const activeCount =
    (params.dateFrom ? 1 : 0) +
    (params.dateTo ? 1 : 0) +
    (params.region ? 1 : 0) +
    (params.order ? 1 : 0);

  return (
    <PageContainer width="page">
      <PageHeader title="Daily Sightings Report" />

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
        <Field label="Region" htmlFor="id_region">
          <Select
            id="id_region"
            value={draft.region}
            onChange={(e) =>
              setDraft((d) => ({ ...d, region: e.target.value }))
            }
          >
            <option value="">All Regions</option>
            {data?.regions.map((region) => (
              <optgroup key={region.id} label={region.name}>
                <option value={region.id}>{region.name}</option>
                {region.sub_regions.map((sub) => (
                  <option key={sub.id} value={sub.id}>
                    &nbsp;&nbsp;{sub.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </Select>
        </Field>
        <Field label="Order" htmlFor="id_order">
          <Select
            id="id_order"
            value={draft.order}
            onChange={(e) =>
              setDraft((d) => ({ ...d, order: e.target.value }))
            }
          >
            <option value="asc">Oldest First</option>
            <option value="desc">Newest First</option>
          </Select>
        </Field>
      </FilterBar>

      {isError && !data ? (
        <ErrorState
          title="Failed to load the report"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          {daily.length > 0 && (
            <StatGrid className="mb-4">
              <StatCard label="Days with Data" value={dayCount} />
              <StatCard label="Avg Apartments/Day" value={aptAvg} />
              <StatCard label="Avg Houses/Day" value={houseAvg} />
              <StatCard label="Total Sightings" value={grandSum} />
            </StatGrid>
          )}

          <Card padding="none" className="overflow-clip">
            <DataTable
              columns={columns}
              rows={daily}
              getRowKey={(day) => day.date}
              loading={isPending}
              empty={
                <EmptyState title="No sightings found for the selected date range." />
              }
              caption="Daily sighting counts"
              mobile="scroll"
            />
          </Card>
        </>
      )}
    </PageContainer>
  );
}
