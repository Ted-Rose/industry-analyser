import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import { fetchProperties, type Kind } from '../api';
import { formatDateYmd, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';

/**
 * React port of property_list.html — the deduplicated property table
 * (apartment or house) with district/street filters. Filters live in
 * the URL; the form stages draft state applied on Filter.
 */
export default function PropertyList({ kind }: { kind: Kind }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    district: searchParams.get('district'),
    street: searchParams.get('street'),
    page: searchParams.get('page'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'properties',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchProperties(kind, params),
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState({
    district: params.district ?? '',
    street: params.street ?? '',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      district: p.get('district') ?? '',
      street: p.get('street') ?? '',
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.district) next.set('district', draft.district);
    if (draft.street) next.set('street', draft.street);
    setSearchParams(next);
  };

  const urls = kindUrls(kind);
  const properties = data?.properties ?? [];

  return (
    <div className="container-fluid py-4">
      <Link to="/" className="back-link">
        ← Back to Classified Ads
      </Link>
      <h2 className="mb-4">
        {data?.kind_label ??
          (kind === 'apartment' ? 'Apartment' : 'House')}{' '}
        Properties ({data?.total_count ?? 0})
      </h2>

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
                  <option value="">All</option>
                  {data?.districts.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-md-3 mb-2">
                <label className="filter-label" htmlFor="id_street">
                  Street contains
                </label>
                <input
                  type="text"
                  id="id_street"
                  className="form-control form-control-sm"
                  value={draft.street}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, street: e.target.value }))
                  }
                />
              </div>
              <div className="col-md-2 mb-2">
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
                >
                  Filter
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load properties — {errorDetail(error)}
        </div>
      )}

      <div className="card filter-card">
        <div className="card-body p-0">
          <div className="table-responsive">
            <table className="table table-hover table-sm mb-0">
              <thead>
                <tr>
                  <th>District</th>
                  <th>Address</th>
                  <th className="text-end">Rooms</th>
                  <th className="text-end">Size m²</th>
                  <th className="text-end">Rent ads</th>
                  <th className="text-end">Sale ads</th>
                  <th>First seen</th>
                  <th>Last seen</th>
                </tr>
              </thead>
              <tbody>
                {properties.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="text-center text-muted py-4"
                    >
                      No properties found — run{' '}
                      <code>link_ads_to_properties</code> first.
                    </td>
                  </tr>
                ) : (
                  properties.map((prop) => (
                    <tr key={prop.id}>
                      <td>{prop.district}</td>
                      <td>
                        <Link to={urls.property(prop.id)}>
                          {prop.street_name} {prop.street_no}
                          {prop.apartment_no
                            ? `, apt ${prop.apartment_no}`
                            : ''}
                        </Link>
                      </td>
                      <td className="text-end">{prop.rooms}</td>
                      <td className="text-end">
                        {formatFloat(prop.size, 1)}
                      </td>
                      <td className="text-end">{prop.rent_ad_count}</td>
                      <td className="text-end">{prop.sale_ad_count}</td>
                      <td>{formatDateYmd(prop.first_seen)}</td>
                      <td>{formatDateYmd(prop.last_seen)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {data && (
        <Pagination
          variant="compact"
          page={data.page}
          numPages={data.num_pages}
          hasPrevious={data.has_previous}
          hasNext={data.has_next}
        />
      )}
    </div>
  );
}
