import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionStatsChildren,
  type Kind,
} from '../api';
import { errorDetail } from '../../shared/api/errors';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import { kindUrls } from '../urls';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';
import DataTable from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import Select from '../../shared/ui/Select';
import { LoadingState } from '../../shared/ui/Skeleton';
import { NoDealTypeNote, statsColumns } from './RegionStats';
import useErrorToast from '../useErrorToast';

interface Draft {
  dateFrom: string;
  dateTo: string;
  dealType: string;
}

/**
 * React port of region_stats_children.html /
 * house_region_stats_children.html — per-sub-region stats for one
 * parent region; rows link through to that child's ads list.
 * date_from/date_to/deal_type live in the URL.
 */
export default function RegionStatsChildren({ kind }: { kind: Kind }) {
  const { regionId } = useParams();
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: (p) => ({
        dateFrom: p.get('date_from') ?? '',
        dateTo: p.get('date_to') ?? '',
        dealType: p.get('deal_type') ?? '',
      }),
      toParams: (d) => {
        const next = new URLSearchParams();
        if (d.dateFrom) next.set('date_from', d.dateFrom);
        if (d.dateTo) next.set('date_to', d.dateTo);
        if (d.dealType) next.set('deal_type', d.dealType);
        return next;
      },
    });
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    dealType: searchParams.get('deal_type'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'region-stats-children',
      kind,
      regionId,
      searchParams.toString(),
    ],
    queryFn: () =>
      fetchRegionStatsChildren(kind, regionId ?? '', params),
    enabled: !!regionId,
  });
  useErrorToast(isError, error, 'Failed to load stats');

  const urls = kindUrls(kind);
  const parent = data?.parent_region;
  const activeCount =
    (params.dateFrom ? 1 : 0) +
    (params.dateTo ? 1 : 0) +
    (params.dealType ? 1 : 0);

  return (
    <PageContainer width="page">
      <PageHeader
        back={
          parent && data
            ? {
                to: `${urls.stats}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}&regions=${parent.id}`,
                label: 'Back to parent regions',
              }
            : undefined
        }
        title={
          parent ? `${parent.name} — Sub-regions` : 'Sub-regions'
        }
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
        data && (
          <>
            <Card padding="none" className="overflow-hidden">
              <DataTable
                columns={statsColumns((row) => (
                  <Link
                    to={`${urls.regionAds(row.region.id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`}
                    className="font-medium text-fg
                      hover:text-accent-text"
                  >
                    {row.region.name}
                  </Link>
                ))}
                rows={data.results}
                getRowKey={(row) => row.region.id}
                empty={<EmptyState title="No sub-regions found." />}
                caption="Sub-region statistics"
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
