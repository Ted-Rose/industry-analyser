import { useQuery } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { fetchAdsTable, type AdOut, type Deal, type Kind } from '../api';
import { formatDate, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { useUrlFilters } from '../../shared/hooks/useUrlFilters';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Button from '../../shared/ui/Button';
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

const TITLES: Record<Kind, Record<Deal, string>> = {
  apartment: {
    rent: 'Apartments for Rent',
    sale: 'Apartments for Sale',
  },
  house: {
    rent: 'Houses for Rent',
    sale: 'Houses for Sale',
  },
};

interface Draft {
  district: string;
  roomsMin: string;
  roomsMax: string;
  sizeMin: string;
  sizeMax: string;
  priceMin: string;
  priceMax: string;
  totalMin: string;
  totalMax: string;
}

/** Draft field ↔ URL param pairs, in display order. The legacy
 *  exact-match `rooms` param folds into rooms_min — "from 2" is what
 *  users meant by picking 2. */
const RANGE_FILTERS = [
  { label: 'Rooms', minKey: 'roomsMin', maxKey: 'roomsMax',
    minParam: 'rooms_min', maxParam: 'rooms_max', step: '1' },
  { label: 'Size m²', minKey: 'sizeMin', maxKey: 'sizeMax',
    minParam: 'size_min', maxParam: 'size_max', step: 'any' },
  { label: '€/m²', minKey: 'priceMin', maxKey: 'priceMax',
    minParam: 'price_min', maxParam: 'price_max', step: 'any' },
  { label: 'Total €', minKey: 'totalMin', maxKey: 'totalMax',
    minParam: 'total_min', maxParam: 'total_max', step: 'any' },
] as const;

function readDraft(p: URLSearchParams): Draft {
  const draft = { district: p.get('district') ?? '' } as Draft;
  for (const f of RANGE_FILTERS) {
    draft[f.minKey] = p.get(f.minParam) ?? '';
    draft[f.maxKey] = p.get(f.maxParam) ?? '';
  }
  if (!draft.roomsMin && p.get('rooms')) {
    draft.roomsMin = p.get('rooms') ?? '';
  }
  return draft;
}

function writeDraft(draft: Draft): URLSearchParams {
  const next = new URLSearchParams();
  if (draft.district) next.set('district', draft.district);
  for (const f of RANGE_FILTERS) {
    if (draft[f.minKey]) next.set(f.minParam, draft[f.minKey]);
    if (draft[f.maxKey]) next.set(f.maxParam, draft[f.maxKey]);
  }
  return next;
}

/** The external View link — one pattern for every out-link. */
function ViewLink({ href }: { href: string }) {
  return (
    <a
      href={href}
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
  );
}

/**
 * React port of the four *_ads_table templates — one component
 * parameterized by kind (apartment|house) and deal (rent|sale), the
 * same way the views were parameterized by model. All filters live in
 * the URL (district, rooms/size/price/total min+max ranges, page);
 * the form stages draft state and applies on Filter, clearing the
 * page — bookmarkable like the old GET form.
 */
export default function AdsTable({
  kind,
  deal,
}: {
  kind: Kind;
  deal: Deal;
}) {
  const { draft, setDraft, apply, reset, searchParams } =
    useUrlFilters<Draft>({
      fromParams: readDraft,
      toParams: writeDraft,
    });
  const params = {
    district: searchParams.get('district'),
    roomsMin: searchParams.get('rooms_min') ?? searchParams.get('rooms'),
    roomsMax: searchParams.get('rooms_max'),
    sizeMin: searchParams.get('size_min'),
    sizeMax: searchParams.get('size_max'),
    priceMin: searchParams.get('price_min'),
    priceMax: searchParams.get('price_max'),
    totalMin: searchParams.get('total_min'),
    totalMax: searchParams.get('total_max'),
    page: searchParams.get('page'),
  };

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: [
      'classified_ads',
      'ads',
      kind,
      deal,
      searchParams.toString(),
    ],
    queryFn: () => fetchAdsTable(kind, deal, params),
  });
  useErrorToast(isError, error, 'Failed to load ads');

  const activeCount =
    (params.district ? 1 : 0) +
    RANGE_FILTERS.filter(
      (f) =>
        searchParams.get(f.minParam) || searchParams.get(f.maxParam),
    ).length +
    (searchParams.get('rooms') ? 1 : 0);
  const hasFilters = activeCount > 0;

  const isApartment = kind === 'apartment';
  const ads = data?.ads ?? [];

  const columns: Column<AdOut>[] = [
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
          {deal === 'rent'
            ? formatFloat(ad.monthly_price_per_sqm, 2)
            : formatFloat(ad.price_per_sqm, 0)}
        </span>
      ),
    },
    {
      id: 'total',
      header: 'Total €',
      align: 'right',
      cell: (ad) => (
        <span className="font-medium">
          {deal === 'rent'
            ? formatFloat(ad.monthly_price, 0)
            : formatFloat(ad.total_price, 0)}
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
      cell: (ad) => <ViewLink href={ad.link} />,
      mobile: 'badge',
    },
  ];

  return (
    <PageContainer width="page">
      <PageHeader
        title={TITLES[kind][deal]}
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
            <option value="">All districts</option>
            {data?.districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
        </Field>

        {RANGE_FILTERS.map((f) => (
          <Field label={f.label} htmlFor={f.minParam} key={f.minParam}>
            <div className="flex gap-2">
              <Input
                type="number"
                id={f.minParam}
                placeholder="From"
                aria-label={`${f.label} from`}
                step={f.step}
                value={draft[f.minKey]}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    [f.minKey]: e.target.value,
                  }))
                }
              />
              <Input
                type="number"
                id={f.maxParam}
                placeholder="To"
                aria-label={`${f.label} to`}
                step={f.step}
                value={draft[f.maxKey]}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d,
                    [f.maxKey]: e.target.value,
                  }))
                }
              />
            </div>
          </Field>
        ))}
      </FilterBar>

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
              rows={ads}
              getRowKey={(ad) => ad.id}
              loading={isPending}
              empty={
                <EmptyState
                  title="No ads match your filters."
                  action={
                    hasFilters ? (
                      <Button
                        variant="secondary"
                        onClick={() => reset()}
                      >
                        Clear filters
                      </Button>
                    ) : undefined
                  }
                />
              }
              caption={TITLES[kind][deal]}
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
