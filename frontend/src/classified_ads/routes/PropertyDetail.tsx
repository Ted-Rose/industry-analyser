import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchProperty, type Kind } from '../api';
import { formatDateYmd, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of property_detail.html — canonical address, attribute
 * list (kind-dependent fields), and the linked-ads table (both deal
 * types, including hidden/misclassified rows — the API intentionally
 * uses all_objects via linked_ads(), like the retired view).
 */
export default function PropertyDetail({ kind }: { kind: Kind }) {
  const { pk } = useParams();
  const navigate = useNavigate();

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['classified_ads', 'property', kind, pk],
    queryFn: () => fetchProperty(kind, pk ?? ''),
    enabled: !!pk,
  });

  const prop = data;
  const address = prop
    ? `${prop.street_name} ${prop.street_no}${
        prop.apartment_no ? `, apt ${prop.apartment_no}` : ''
      }`
    : '';

  return (
    <div className="container py-4">
      <button
        type="button"
        className="btn btn-link back-link p-0"
        onClick={() => navigate(-1)}
      >
        ← Back
      </button>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load the property — {errorDetail(error)}
        </div>
      )}
      {isPending && <p className="text-muted">Loading…</p>}

      {prop && (
        <>
          <h2 className="mb-1">{address}</h2>
          <p className="text-muted mb-4">
            {prop.district}
            {prop.region_name ? ` · ${prop.region_name}` : ''}
          </p>

          <div className="card filter-card mb-4">
            <div className="card-body">
              <dl className="prop-attrs row mb-0">
                <dt className="col-sm-3">Rooms</dt>
                <dd className="col-sm-3">{prop.rooms}</dd>
                <dt className="col-sm-3">Size</dt>
                <dd className="col-sm-3">
                  {formatFloat(prop.size, 1)} m²
                </dd>
                {kind === 'apartment' && (
                  <>
                    <dt className="col-sm-3">Floor</dt>
                    <dd className="col-sm-3">
                      {prop.floor} / {prop.max_floor}
                    </dd>
                  </>
                )}
                {kind === 'house' && (
                  <>
                    <dt className="col-sm-3">Floors</dt>
                    <dd className="col-sm-3">{prop.floors}</dd>
                  </>
                )}
                {kind === 'house' && prop.land_area_sqm != null && (
                  <>
                    <dt className="col-sm-3">Land</dt>
                    <dd className="col-sm-3">
                      {formatFloat(prop.land_area_sqm, 0)} m²
                    </dd>
                  </>
                )}
                <dt className="col-sm-3">Days on market</dt>
                <dd className="col-sm-3">{prop.days_on_market}</dd>
                <dt className="col-sm-3">First seen</dt>
                <dd className="col-sm-3">
                  {formatDateYmd(prop.first_seen)}
                </dd>
                <dt className="col-sm-3">Last seen</dt>
                <dd className="col-sm-3">
                  {formatDateYmd(prop.last_seen)}
                </dd>
              </dl>
            </div>
          </div>

          <h4 className="mb-3">Linked ads ({prop.ad_rows.length})</h4>
          <div className="card filter-card">
            <div className="card-body p-0">
              <div className="table-responsive">
                <table className="table table-hover table-sm mb-0">
                  <thead>
                    <tr>
                      <th>Ad</th>
                      <th>Deal</th>
                      <th className="text-end">Price</th>
                      <th>Match</th>
                      <th className="text-end">Score</th>
                      <th>First seen</th>
                      <th>Last seen</th>
                      <th className="text-end">Days seen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {prop.ad_rows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={8}
                          className="text-center text-muted py-4"
                        >
                          No linked ads.
                        </td>
                      </tr>
                    ) : (
                      prop.ad_rows.map((row) => (
                        <tr key={`${row.deal}-${row.ad_id}`}>
                          <td>
                            <a
                              href={row.link}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {/* truncatechars:30 — 29 chars + '…' */}
                              {row.ad_id.length > 30
                                ? `${row.ad_id.slice(0, 29)}…`
                                : row.ad_id}
                            </a>
                          </td>
                          <td>{row.deal}</td>
                          <td className="text-end">
                            €{formatFloat(row.price, 0)}
                            {row.price_suffix}
                          </td>
                          <td>{row.match_status}</td>
                          <td className="text-end">
                            {row.match_score != null
                              ? formatFloat(row.match_score, 2)
                              : '—'}
                          </td>
                          <td>{formatDateYmd(row.first_seen)}</td>
                          <td>{formatDateYmd(row.last_seen)}</td>
                          <td className="text-end">
                            {row.days_active}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
