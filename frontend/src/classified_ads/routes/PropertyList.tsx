import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchProperties,
  type Kind,
  type PropertyRowOut,
} from '../api';
import { formatDateYmd, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import { kindUrls } from '../urls';
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
import Pagination from '../../shared/ui/Pagination';
import Select from '../../shared/ui/Select';
import useErrorToast from '../useErrorToast';

interface Draft {
  district: string;
  street: string;
}

/**
 * React port of property_list.html — the deduplicated property table
 * (apartment or house) with district/street filters. Filters live in
 * the URL; the form stages draft state applied on Filter.
 */
export default function PropertyList({ kind }: { kind: Kind }) {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: (p) => ({
        district: p.get('district') ?? '',
        street: p.get('street') ?? '',
      }),
      toParams: (d) => {
        const next = new URLSearchParams();
        if (d.district) next.set('district', d.district);
        if (d.street) next.set('street', d.street);
        return next;
      },
    });
  const params = {
    district: searchParams.get('district'),
    street: searchParams.get('street'),
    page: searchParams.get('page'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'properties',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchProperties(kind, params),
  });
  useErrorToast(isError, error, 'Failed to load properties');

  const urls = kindUrls(kind);
  const properties = data?.properties ?? [];
  const activeCount =
    (params.district ? 1 : 0) + (params.street ? 1 : 0);

  const columns: Column<PropertyRowOut>[] = [
    {
      id: 'district',
      header: 'District',
      cell: (prop) => prop.district,
      mobile: 'subtitle',
    },
    {
      id: 'address',
      header: 'Address',
      cell: (prop) => (
        <Link
          to={urls.property(prop.id)}
          className="font-medium text-fg hover:text-accent-text"
        >
          {prop.street_name} {prop.street_no}
          {prop.apartment_no ? `, apt ${prop.apartment_no}` : ''}
        </Link>
      ),
      mobile: 'title',
    },
    {
      id: 'rooms',
      header: 'Rooms',
      align: 'right',
      cell: (prop) => prop.rooms,
    },
    {
      id: 'size',
      header: 'Size m²',
      align: 'right',
      cell: (prop) => formatFloat(prop.size, 1),
    },
    {
      id: 'rent_ads',
      header: 'Rent ads',
      align: 'right',
      cell: (prop) => prop.rent_ad_count,
    },
    {
      id: 'sale_ads',
      header: 'Sale ads',
      align: 'right',
      cell: (prop) => prop.sale_ad_count,
    },
    {
      id: 'first_seen',
      header: 'First seen',
      cell: (prop) => (
        <span className="text-fg-subtle">
          {formatDateYmd(prop.first_seen)}
        </span>
      ),
      mobile: 'meta',
    },
    {
      id: 'last_seen',
      header: 'Last seen',
      cell: (prop) => (
        <span className="text-fg-subtle">
          {formatDateYmd(prop.last_seen)}
        </span>
      ),
      mobile: 'meta',
    },
  ];

  return (
    <PageContainer width="page">
      <PageHeader
        back={{ to: '/', label: 'Back to Classified Ads' }}
        title={`${
          data?.kind_label ??
          (kind === 'apartment' ? 'Apartment' : 'House')
        } Properties`}
        description={
          data
            ? `${data.total_count} result${
                data.total_count === 1 ? '' : 's'
              }`
            : undefined
        }
      />

      <FilterBar
        onSubmit={apply}
        onReset={reset}
        activeCount={activeCount}
        collapsible="mobile"
        submitLabel="Filter"
        resetLabel="Clear filters"
        className="mb-4"
      >
        <Field label="District" htmlFor="id_district">
          <Select
            id="id_district"
            value={draft.district}
            onChange={(e) =>
              setDraft((d) => ({ ...d, district: e.target.value }))
            }
          >
            <option value="">All</option>
            {data?.districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Street contains" htmlFor="id_street">
          <Input
            id="id_street"
            value={draft.street}
            onChange={(e) =>
              setDraft((d) => ({ ...d, street: e.target.value }))
            }
          />
        </Field>
      </FilterBar>

      {isError && !data ? (
        <ErrorState
          title="Failed to load properties"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <>
          <Card padding="none" className="overflow-clip">
            <DataTable
              columns={columns}
              rows={properties}
              getRowKey={(prop) => prop.id}
              loading={isPending}
              empty={
                <EmptyState
                  title={
                    <>
                      No properties found — run{' '}
                      <code>link_ads_to_properties</code> first.
                    </>
                  }
                />
              }
              caption={
                kind === 'apartment'
                  ? 'Apartment properties'
                  : 'House properties'
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
