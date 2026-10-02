import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import Pagination from '../components/Pagination';
import { fetchRegionAds, type AdOut, type Kind } from '../api';
import { formatDate, formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';

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

  const { data, isPending, isError, error } = useQuery({
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

  const urls = kindUrls(kind);
  const isApartment = kind === 'apartment';
  const region = data?.region;
  const colSpan = isApartment ? 12 : 11;

  const backTarget =
    data && region
      ? region.parent_id
        ? `${urls.statsChildren(region.parent_id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`
        : `${urls.stats}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}&regions=${region.id}`
      : urls.stats;
  const backLabel = region?.parent_id
    ? `← Back to ${region.parent_name}`
    : '← Back to region stats';

  return (
    <div className="container-fluid py-4">
      <Link to={backTarget} className="back-link">
        {backLabel}
      </Link>

      <div className="d-flex align-items-center mb-3">
        <h2 className="mb-0 me-3">
          {region ? `${region.name} - Ads` : 'Ads'}
        </h2>
        <span className="result-count">
          {data
            ? `${data.total_count} result${data.total_count === 1 ? '' : 's'}`
            : ''}
        </span>
      </div>

      {data && (
        <div className="alert alert-info">
          <strong>Time period:</strong> {data.date_from} to{' '}
          {data.date_to}
          {data.deal_type && (
            <>
              <br />
              <strong>Deal type:</strong> {data.deal_type}
            </>
          )}
        </div>
      )}

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
                  {isApartment && <th>Type</th>}
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
                {data && data.ads.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={colSpan}
                      className="text-center text-muted py-4"
                    >
                      No ads found for this region in the selected time
                      period.
                    </td>
                  </tr>
                ) : (
                  data?.ads.map((ad) => (
                    <RegionAdRow
                      key={ad.id}
                      ad={ad}
                      isApartment={isApartment}
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
          variant="caps"
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
 * Both deal types show the sale-equivalent columns
 * (price_per_sqm/total_price) — matching the retired template, which
 * rendered those fields for rent ads too.
 */
function RegionAdRow({
  ad,
  isApartment,
}: {
  ad: AdOut;
  isApartment: boolean;
}) {
  const street = ad.street_no
    ? `${ad.street_name} ${ad.street_no}`
    : ad.street_name;
  return (
    <tr>
      {isApartment && (
        <td>
          {ad.deal === 'Rent' ? (
            <span className="badge bg-info">Rent</span>
          ) : (
            <span className="badge bg-success">Sell</span>
          )}
        </td>
      )}
      <td>{ad.district}</td>
      <td>{street}</td>
      <td className="text-center">{ad.rooms}</td>
      <td className="text-end">{formatFloat(ad.size, 1)}</td>
      {isApartment ? (
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
      <td className="text-end fw-bold">
        {formatFloat(ad.price_per_sqm, 0)}
      </td>
      <td className="text-end fw-bold">
        {formatFloat(ad.total_price, 0)}
      </td>
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
