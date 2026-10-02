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
  rooms: string;
  priceMin: string;
  priceMax: string;
}

/**
 * React port of the four *_ads_table templates — one component
 * parameterized by kind (apartment|house) and deal (rent|sale), the
 * same way the views were parameterized by model. All filters live in
 * the URL (district/rooms/price_min/price_max/page); the form stages
 * draft state and applies on Filter, clearing the page — bookmarkable
 * like the old GET form.
 */
export default function AdsTable({ kind, deal }: { kind: Kind; deal: Deal }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    district: searchParams.get('district'),
    rooms: searchParams.get('rooms'),
    priceMin: searchParams.get('price_min'),
    priceMax: searchParams.get('price_max'),
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
  const [draft, setDraft] = useState<Draft>({
    district: params.district ?? '',
    rooms: params.rooms ?? '',
    priceMin: params.priceMin ?? '',
    priceMax: params.priceMax ?? '',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      district: p.get('district') ?? '',
      rooms: p.get('rooms') ?? '',
      priceMin: p.get('price_min') ?? '',
      priceMax: p.get('price_max') ?? '',
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.district) next.set('district', draft.district);
    if (draft.rooms) next.set('rooms', draft.rooms);
    if (draft.priceMin) next.set('price_min', draft.priceMin);
    if (draft.priceMax) next.set('price_max', draft.priceMax);
    // Filters changed — land back on page 1.
    setSearchParams(next);
  };

  const clearFilters = () => setSearchParams(new URLSearchParams());

  const hasFilters =
    !!params.district ||
    !!params.rooms ||
    !!params.priceMin ||
    !!params.priceMax;

  const isApartment = kind === 'apartment';
  const pricePlaceholders =
    deal === 'rent' ? ['e.g. 5', 'e.g. 20'] : ['e.g. 500', 'e.g. 2000'];
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

              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_rooms">
                  Rooms
                </label>
                <select
                  id="id_rooms"
                  className="form-control form-control-sm"
                  value={draft.rooms}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, rooms: e.target.value }))
                  }
                >
                  <option value="">Any</option>
                  {data?.room_choices.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>

              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_price_min">
                  €/m² min
                </label>
                <input
                  type="number"
                  id="id_price_min"
                  className="form-control form-control-sm"
                  placeholder={pricePlaceholders[0]}
                  value={draft.priceMin}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, priceMin: e.target.value }))
                  }
                />
              </div>

              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_price_max">
                  €/m² max
                </label>
                <input
                  type="number"
                  id="id_price_max"
                  className="form-control form-control-sm"
                  placeholder={pricePlaceholders[1]}
                  value={draft.priceMax}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, priceMax: e.target.value }))
                  }
                />
              </div>

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
