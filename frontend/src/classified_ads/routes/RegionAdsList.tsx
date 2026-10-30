import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { fetchRegionAds, type AdOut, type Kind } from '../api';
import { formatDate, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge from '../../shared/ui/Badge';
import Card from '../../shared/ui/Card';
import DataTable, { type Column } from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState, { Alert } from '../../shared/ui/ErrorState';
import Pagination from '../../shared/ui/Pagination';
import useErrorToast from '../useErrorToast';

/**
 * React port of region_ads_list.html / house_region_ads_list.html —
 * ads first-seen inside the window across a region subtree. No filter
 * form: date_from/date_to/deal_type arrive in the URL from the stats
 * pages and only pagination changes them.
 *
 * Deliberate fix vs. the template: the old markup tested
 * `ad.deal_type` — an attribute the models never had — so every row
 * rendered the 'Sell' badge. The API now returns the real deal.
 */
export default function RegionAdsList({ kind }: { kind: Kind }) {
  const { regionId } = useParams();
  const [searchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    dealType: searchParams.get('deal_type'),
    page: searchParams.get('page'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'region-ads',
      kind,
      regionId,
      searchParams.toString(),
    ],
    queryFn: () => fetchRegionAds(kind, regionId ?? '', params),
    enabled: !!regionId,
  });
  useErrorToast(isError, error, 'Failed to load ads');

  const urls = kindUrls(kind);
  const isApartment = kind === 'apartment';
  const region = data?.region;

  const backTarget =
    data && region
      ? region.parent_id
        ? `${urls.statsChildren(region.parent_id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`
        : `${urls.stats}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}&regions=${region.id}`
      : urls.stats;
  const backLabel = region?.parent_id
    ? `Back to ${region.parent_name}`
    : 'Back to region stats';

  const columns: Column<AdOut>[] = [
    ...(isApartment
      ? [
          {
            id: 'type',
            header: 'Type',
            cell: (ad: AdOut) =>
              ad.deal === 'Rent' ? (
                <Badge tone="info">Rent</Badge>
              ) : (
                <Badge tone="success">Sell</Badge>
              ),
            mobile: 'badge' as const,
          },
        ]
      : []),
    {
      id: 'district',
      header: 'District',
      cell: (ad) => ad.district,
      mobile: 'subtitle',
    },
    {
      id: 'street',
      header: 'Street',
      cell: (ad) =>
        ad.street_no
          ? `${ad.street_name} ${ad.street_no}`
          : ad.street_name,
      mobile: 'title',
    },
    {
      id: 'rooms',
      header: 'Rooms',
      align: 'right',
      cell: (ad) => ad.rooms,
    },
    {
      id: 'size',
      header: 'Size m²',
      align: 'right',
      cell: (ad) => formatFloat(ad.size, 1),
    },
    isApartment
      ? {
          id: 'floor',
          header: 'Floor',
          align: 'right' as const,
          cell: (ad: AdOut) => `${ad.floor}/${ad.max_floor}`,
        }
      : {
          id: 'floors',
          header: 'Floors',
          align: 'right' as const,
          cell: (ad: AdOut) => ad.floors,
        },
    isApartment
      ? {
          id: 'project',
          header: 'Project',
          cell: (ad: AdOut) => ad.project ?? '—',
        }
      : {
          id: 'land',
          header: 'Land Area m²',
          align: 'right' as const,
          cell: (ad: AdOut) => formatFloat(ad.land_area_sqm, 0),
        },
    {
      id: 'sqm',
      header: '€/m²',
      align: 'right',
      cell: (ad) => (
        <span className="font-medium">
          {formatFloat(ad.price_per_sqm, 0)}
        </span>
      ),
    },
    {
      id: 'total',
      header: 'Total €',
      align: 'right',
      cell: (ad) => (
        <span className="font-medium">
          {formatFloat(ad.total_price, 0)}
        </span>
      ),
    },
    {
      id: 'posted',
      header: 'Posted',
      cell: (ad) => formatDate(ad.post_date),
      mobile: 'meta',
    },
    {
      id: 'days',
      header: 'Days active',
      align: 'right',
      cell: (ad) => ad.days_active,
    },
    {
      id: 'link',
      header: 'Link',
      cell: (ad) => (
        <a
          href={ad.link}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent-text hover:text-accent-hover"
        >
          View
          <ExternalLink
            className="ml-0.5 inline size-3"
            aria-hidden="true"
          />
        </a>
      ),
      ...(isApartment ? {} : { mobile: 'badge' as const }),
    },
  ];

  return (
    <PageContainer width="page">
      <PageHeader
        back={{ to: backTarget, label: backLabel }}
        title={region ? `${region.name} - Ads` : 'Ads'}
        description={
          data
            ? `${data.total_count} result${
                data.total_count === 1 ? '' : 's'
              }`
            : undefined
        }
      />

      {data && (
        <Alert tone="info" className="mb-4">
          <strong>Time period:</strong> {data.date_from} to{' '}
          {data.date_to}
          {data.deal_type && (
            <>
              <br />
              <strong>Deal type:</strong> {data.deal_type}
            </>
          )}
        </Alert>
      )}

      {isError && !data ? (
        <ErrorState
          title="Failed to load ads"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <Card padding="none" className="overflow-hidden">
            <DataTable
              columns={columns}
              rows={data?.ads ?? []}
              getRowKey={(ad) => ad.id}
              loading={isPending}
              empty={
                <EmptyState title="No ads found for this region in the selected time period." />
              }
              caption={
                region ? `${region.name} — ads` : 'Region ads'
              }
              mobile="cards"
              className="max-md:p-3"
            />
          </Card>
          {data && (
            <Pagination
              page={data.page}
              numPages={data.num_pages}
              className="mt-4"
            />
          )}
        </>
      )}
    </PageContainer>
  );
}
