import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import { fetchAdsTable, type AdOut, type Deal, type Kind } from '../api';
import { formatDate, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';

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

/**
 * React port of the four *_ads_table templates — one component
 * parameterized by kind (apartment|house) and deal (rent|sale), the
 * same way the views were parameterized by model. All filters live in
 * the URL (district, rooms/size/price/total min+max ranges, page);
 * the form stages draft state and applies on Filter, clearing the
 * page — bookmarkable like the old GET form.
 */
export default function AdsTable({ kind, deal }: { kind: Kind; deal: Deal }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const draft0 = readDraft(searchParams);
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

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'ads',
      kind,
      deal,
      searchParams.toString(),
    ],
    queryFn: () => fetchAdsTable(kind, deal, params),
  });

  // Staged filter state — mirrors the GET form: nothing applies until
  // Filter is pressed. Re-synced when the URL changes (pagination,
  // back/forward).
  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>(draft0);
  useEffect(() => {
    setDraft(readDraft(new URLSearchParams(paramsKey)));
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.district) next.set('district', draft.district);
    for (const f of RANGE_FILTERS) {
      if (draft[f.minKey]) next.set(f.minParam, draft[f.minKey]);
      if (draft[f.maxKey]) next.set(f.maxParam, draft[f.maxKey]);
    }
    // Filters changed — land back on page 1.
    setSearchParams(next);
  };

  const clearFilters = () => setSearchParams(new URLSearchParams());

  const hasFilters =
    !!params.district ||
    RANGE_FILTERS.some(
      (f) => searchParams.get(f.minParam) || searchParams.get(f.maxParam),
    ) ||
    !!searchParams.get('rooms');

  const isApartment = kind === 'apartment';
  const colSpan = 11;

  const ads = data?.ads ?? [];

  return (
    <div className="container-fluid py-4">
      <div className="d-flex align-items-center mb-3">
        <h2 className="mb-0 me-3">{TITLES[kind][deal]}</h2>
        <span className="result-count">
          {data ? `${data.total_count} result${data.total_count === 1 ? '' : 's'}` : ''}
        </span>
      </div>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form onSubmit={applyFilters}>
            <div className="row align-items-end">
              <div className="col-md-3 mb-2">
                <label className="filter-label" htmlFor="id_district">
                  District
                </label>
                <select
                  id="id_district"
                  className="form-control form-control-sm"
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
                </select>
              </div>

              {RANGE_FILTERS.map((f) => (
                <div className="col-md-2 mb-2" key={f.minParam}>
                  <label className="filter-label" htmlFor={f.minParam}>
                    {f.label}
                  </label>
                  <div className="d-flex gap-1">
                    <input
                      type="number"
                      id={f.minParam}
                      className="form-control form-control-sm"
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
                    <input
                      type="number"
                      id={f.maxParam}
                      className="form-control form-control-sm"
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
                </div>
              ))}

              <div className="col-md-1 mb-2 d-flex align-items-end">
                <button
                  type="submit"
                  className="btn btn-primary btn-sm w-100"
                >
                  Filter
                </button>
              </div>
            </div>

            {hasFilters && (
              <div className="mt-1">
                <button
                  type="button"
                  className="btn btn-link btn-sm p-0 text-secondary"
                  onClick={clearFilters}
                >
                  ✕ Clear filters
                </button>
              </div>
            )}
          </form>
        </div>
      </div>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load ads — {errorDetail(error)}
        </div>
      )}

      {/* Table */}
      <div className="card filter-card">
        <div className="card-body p-0">
          <div className="table-responsive">
            <table className="table table-hover table-sm mb-0">
              <thead>
                <tr>
                  <th>District</th>
                  <th>Street</th>
                  <th>Rooms</th>
                  <th>Size m²</th>
                  {isApartment ? (
                    <>
                      <th>Floor</th>
                      <th>Project</th>
                    </>
                  ) : (
                    <>
                      <th>Floors</th>
                      <th>Land Area m²</th>
                    </>
                  )}
                  <th>€/m²</th>
                  <th>Total €</th>
                  <th>Posted</th>
                  <th>Days active</th>
                  <th>Link</th>
                </tr>
              </thead>
              <tbody>
                {ads.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={colSpan}
                      className="text-center text-muted py-4"
                    >
                      No ads match your filters.
                    </td>
                  </tr>
                ) : (
                  ads.map((ad) => (
                    <AdRow
                      key={ad.id}
                      ad={ad}
                      kind={kind}
                      deal={deal}
                    />
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {data && (
        <Pagination
          page={data.page}
          numPages={data.num_pages}
          hasPrevious={data.has_previous}
          hasNext={data.has_next}
        />
      )}
    </div>
  );
}

/**
 * One ads-table row — rent deals show monthly prices
 * (floatformat:2/0), sale deals the sale columns (floatformat:0).
 */
function AdRow({
  ad,
  kind,
  deal,
}: {
  ad: AdOut;
  kind: Kind;
  deal: Deal;
}) {
  const street = ad.street_no
    ? `${ad.street_name} ${ad.street_no}`
    : ad.street_name;
  return (
    <tr>
      <td>{ad.district}</td>
      <td>{street}</td>
      <td className="text-center">{ad.rooms}</td>
      <td className="text-end">{formatFloat(ad.size, 1)}</td>
      {kind === 'apartment' ? (
        <>
          <td className="text-center">
            {ad.floor}/{ad.max_floor}
          </td>
          <td>{ad.project ?? '—'}</td>
        </>
      ) : (
        <>
          <td className="text-center">{ad.floors}</td>
          <td className="text-end">
            {formatFloat(ad.land_area_sqm, 0)}
          </td>
        </>
      )}
      {deal === 'rent' ? (
        <>
          <td className="text-end fw-bold">
            {formatFloat(ad.monthly_price_per_sqm, 2)}
          </td>
          <td className="text-end fw-bold">
            {formatFloat(ad.monthly_price, 0)}
          </td>
        </>
      ) : (
        <>
          <td className="text-end fw-bold">
            {formatFloat(ad.price_per_sqm, 0)}
          </td>
          <td className="text-end fw-bold">
            {formatFloat(ad.total_price, 0)}
          </td>
        </>
      )}
      <td>{formatDate(ad.post_date)}</td>
      <td className="text-center">{ad.days_active}</td>
      <td>
        <a
          href={ad.link}
          target="_blank"
          rel="noopener noreferrer"
          className="ad-link"
        >
          View
        </a>
      </td>
    </tr>
  );
}
