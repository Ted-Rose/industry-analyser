import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import {
  fetchProperty,
  type Kind,
  type LinkedAdOut,
} from '../api';
import { formatDateYmd, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge from '../../shared/ui/Badge';
import Card from '../../shared/ui/Card';
import DataTable, { type Column } from '../../shared/ui/DataTable';
import DescriptionList from '../../shared/ui/DescriptionList';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';
import useErrorToast from '../useErrorToast';

/**
 * React port of property_detail.html — canonical address, attribute
 * list (kind-dependent fields), and the linked-ads table (both deal
 * types, including hidden/misclassified rows — the API intentionally
 * uses all_objects via linked_ads(), like the retired view).
 */
export default function PropertyDetail({ kind }: { kind: Kind }) {
  const { pk } = useParams();
  const urls = kindUrls(kind);

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['classified_ads', 'property', kind, pk],
    queryFn: () => fetchProperty(kind, pk ?? ''),
    enabled: !!pk,
  });
  useErrorToast(isError, error, 'Failed to load the property');

  const prop = data;
  const address = prop
    ? `${prop.street_name} ${prop.street_no}${
        prop.apartment_no ? `, apt ${prop.apartment_no}` : ''
      }`
    : '';

  const columns: Column<LinkedAdOut>[] = [
    {
      id: 'ad',
      header: 'Ad',
      cell: (row) => (
        <a
          href={row.link}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-fg hover:text-accent-text"
        >
          {/* truncatechars:30 — 29 chars + '…' */}
          {row.ad_id.length > 30
            ? `${row.ad_id.slice(0, 29)}…`
            : row.ad_id}
          <ExternalLink
            className="ml-0.5 inline size-3"
            aria-hidden="true"
          />
        </a>
      ),
      mobile: 'title',
    },
    {
      id: 'deal',
      header: 'Deal',
      cell: (row) =>
        row.deal === 'Rent' ? (
          <Badge tone="info">Rent</Badge>
        ) : (
          <Badge tone="success">Sell</Badge>
        ),
      mobile: 'badge',
    },
    {
      id: 'price',
      header: 'Price',
      align: 'right',
      cell: (row) => (
        <>
          €{formatFloat(row.price, 0)}
          {row.price_suffix}
        </>
      ),
    },
    {
      id: 'match',
      header: 'Match',
      cell: (row) => row.match_status,
    },
    {
      id: 'score',
      header: 'Score',
      align: 'right',
      cell: (row) =>
        row.match_score != null
          ? formatFloat(row.match_score, 2)
          : '—',
    },
    {
      id: 'first_seen',
      header: 'First seen',
      cell: (row) => formatDateYmd(row.first_seen),
      mobile: 'meta',
    },
    {
      id: 'last_seen',
      header: 'Last seen',
      cell: (row) => formatDateYmd(row.last_seen),
      mobile: 'meta',
    },
    {
      id: 'days',
      header: 'Days seen',
      align: 'right',
      cell: (row) => row.days_active,
    },
  ];

  return (
    <PageContainer width="page">
      <PageHeader
        back={{ to: urls.properties, label: 'Back to properties' }}
        title={address || 'Property'}
        description={
          prop
            ? `${prop.district}${
                prop.region_name ? ` · ${prop.region_name}` : ''
              }`
            : undefined
        }
      />

      {isError && !prop ? (
        <ErrorState
          title="Failed to load the property"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : isPending ? (
        <LoadingState variant="table" />
      ) : (
        prop && (
          <>
            <Card className="mb-4">
              <DescriptionList
                items={[
                  { term: 'Rooms', description: prop.rooms },
                  {
                    term: 'Size',
                    description: `${formatFloat(prop.size, 1)} m²`,
                  },
                  ...(kind === 'apartment'
                    ? [
                        {
                          term: 'Floor',
                          description: `${prop.floor} / ${prop.max_floor}`,
                        },
                      ]
                    : [
                        {
                          term: 'Floors',
                          description: prop.floors,
                        },
                        ...(prop.land_area_sqm != null
                          ? [
                              {
                                term: 'Land',
                                description: `${formatFloat(
                                  prop.land_area_sqm,
                                  0,
                                )} m²`,
                              },
                            ]
                          : []),
                      ]),
                  {
                    term: 'Days on market',
                    description: prop.days_on_market,
                  },
                  {
                    term: 'First seen',
                    description: formatDateYmd(prop.first_seen),
                  },
                  {
                    term: 'Last seen',
                    description: formatDateYmd(prop.last_seen),
                  },
                ]}
              />
            </Card>

            <h2 className="mb-3 text-xl font-semibold">
              Linked ads ({prop.ad_rows.length})
            </h2>
            <Card padding="none" className="overflow-hidden">
              <DataTable
                columns={columns}
                rows={prop.ad_rows}
                getRowKey={(row) => `${row.deal}-${row.ad_id}`}
                empty={<EmptyState title="No linked ads." />}
                caption="Linked ads"
                mobile="cards"
                className="max-md:p-3"
              />
            </Card>
          </>
        )
      )}
    </PageContainer>
  );
}
