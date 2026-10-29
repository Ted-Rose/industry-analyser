import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRentVsBuyRanked,
  type Kind,
  type RentVsBuyRankedRowOut,
} from '../api';
import { formatFloat } from '../format';
import { errorDetail } from '../../shared/api/errors';
import { kindUrls } from '../urls';

const KINDS: { kind: Kind; label: string }[] = [
  { kind: 'apartment', label: 'Apartments' },
  { kind: 'house', label: 'Houses' },
];

/** Rows under both thresholds on both ad sides are excluded by the
 *  API already (min_ads); rows that pass the gate but stay thin
 *  (<20 on either side) or compare unlike sizes are de-emphasized. */
const THIN_AD_COUNT = 20;
const TOP_HIGHLIGHT = 10;

function isThin(row: RentVsBuyRankedRowOut): boolean {
  return row.n_rent_ads < THIN_AD_COUNT || row.n_sale_ads < THIN_AD_COUNT;
}

function isFlagged(row: RentVsBuyRankedRowOut): boolean {
  return !row.size_comparable || isThin(row);
}

/**
 * Ranked rent-vs-buy report — the API returns cells of (exact
 * region node x property type) pre-sorted ascending by
 * months_to_buyout: how many months of the median rent it takes
 * to buy the median unit outright. Filters live in the URL
 * (kind/days/min_ads/residual).
 */
export default function RentVsBuy() {
  const [searchParams, setSearchParams] = useSearchParams();
  const kind: Kind =
    searchParams.get('kind') === 'house' ? 'house' : 'apartment';
  const params = {
    days: searchParams.get('days'),
    minAds: searchParams.get('min_ads'),
    includeResidual: searchParams.get('residual') === '1',
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'rent-vs-buy-ranked',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchRentVsBuyRanked(kind, params),
  });

  const urls = kindUrls(kind);
  const applyFilters = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const next = new URLSearchParams();
    next.set('kind', kind);
    const days = String(form.get('days') ?? '');
    const minAds = String(form.get('min_ads') ?? '');
    if (days) next.set('days', days);
    if (minAds) next.set('min_ads', minAds);
    if (form.get('residual')) next.set('residual', '1');
    setSearchParams(next);
  };

  const kindUrl = (k: Kind) => {
    const next = new URLSearchParams(searchParams);
    next.set('kind', k);
    return `?${next}`;
  };

  return (
    <div className="container-fluid py-4">
      <Link to="/" className="back-link">
        ← Back to Classified Ads
      </Link>
      <div className="d-flex align-items-center mb-3">
        <h2 className="mb-0 me-3">Rent vs Buy — ranked</h2>
        <div className="btn-group btn-group-sm" role="group">
          {KINDS.map((k) => (
            <Link
              key={k.kind}
              to={kindUrl(k.kind)}
              className={
                'btn ' +
                (kind === k.kind ? 'btn-primary' : 'btn-outline-primary')
              }
            >
              {k.label}
            </Link>
          ))}
        </div>
      </div>
      <p className="text-muted">
        Months of median rent needed to buy the median unit
        outright, per region x property type — lower means buying
        looks cheap relative to renting. Only cells with at least
        the minimum ad count on both sides are ranked.
      </p>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form onSubmit={applyFilters}>
            <div className="row align-items-end">
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_days">
                  Window (days)
                </label>
                <input
                  type="number"
                  id="id_days"
                  name="days"
                  min="1"
                  max="365"
                  className="form-control form-control-sm"
                  defaultValue={params.days ?? '30'}
                />
              </div>
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_min_ads">
                  Min ads per side
                </label>
                <input
                  type="number"
                  id="id_min_ads"
                  name="min_ads"
                  min="1"
                  className="form-control form-control-sm"
                  defaultValue={params.minAds ?? '15'}
                />
              </div>
              <div className="col-md-3 mb-2">
                <label className="filter-label d-block">
                  <input
                    type="checkbox"
                    name="residual"
                    value="1"
                    defaultChecked={params.includeResidual}
                  />{' '}
                  Include residual regions
                </label>
              </div>
              <div className="col-md-1 mb-2">
                <button
                  type="submit"
                  className="btn btn-primary btn-sm w-100"
                >
                  Apply
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load ranking — {errorDetail(error)}
        </div>
      )}
      {isPending && <p className="text-muted">Loading…</p>}

      {data && (
        <>
          <RankedTable
            rows={data.results}
            kind={kind}
            regionAds={urls.regionAds}
            emptyText={
              'No cells pass the minimum ad count in this window.'
            }
            showRank
          />
          {data.residual.length > 0 && (
            <>
              <h5 className="mt-4">
                Residual regions (ads on parent-level or unset
                regions — not ranked)
              </h5>
              <RankedTable
                rows={data.residual}
                kind={kind}
                regionAds={urls.regionAds}
                emptyText=""
              />
            </>
          )}
          <CaveatNote
            dateFrom={data.date_from}
            dateTo={data.date_to}
            minAds={data.min_ads}
          />
        </>
      )}
    </div>
  );
}

function RankedTable({
  rows,
  kind,
  regionAds,
  emptyText,
  showRank = false,
}: {
  rows: RentVsBuyRankedRowOut[];
  kind: Kind;
  regionAds: (regionId: number) => string;
  emptyText: string;
  showRank?: boolean;
}) {
  return (
    <div className="card filter-card">
      <div className="card-body p-0">
        <div className="table-responsive">
          <table className="table table-hover table-sm mb-0">
            <thead>
              <tr>
                {showRank && <th>#</th>}
                <th>Region</th>
                <th>{kind === 'apartment' ? 'Project' : 'House type'}</th>
                <th className="text-end">Months to buy</th>
                <th className="text-end">Years</th>
                <th className="text-end">Med rent €/mo</th>
                <th className="text-end">Med price €</th>
                <th className="text-end">Rent €/m²</th>
                <th className="text-end">Sale €/m²</th>
                <th className="text-end">Rent m²</th>
                <th className="text-end">Sale m²</th>
                <th className="text-end">n rent</th>
                <th className="text-end">n sale</th>
                <th className="text-end">Paired mo.</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td
                    colSpan={showRank ? 15 : 14}
                    className="text-center text-muted py-4"
                  >
                    {emptyText}
                  </td>
                </tr>
              ) : (
                rows.map((row, i) => (
                  <Row
                    key={`${row.region?.id ?? 'none'}-${
                      row.property_type
                    }`}
                    row={row}
                    rank={showRank ? i + 1 : null}
                    regionAds={regionAds}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function Row({
  row,
  rank,
  regionAds,
}: {
  row: RentVsBuyRankedRowOut;
  rank: number | null;
  regionAds: (regionId: number) => string;
}) {
  const flagged = isFlagged(row);
  const highlighted =
    !flagged && rank !== null && rank <= TOP_HIGHLIGHT;
  const flags: string[] = [];
  if (!row.size_comparable) flags.push('size gap');
  if (isThin(row)) flags.push('thin data');
  return (
    <tr
      className={
        highlighted ? 'table-success' : flagged ? 'text-muted' : ''
      }
      title={flags.length ? flags.join(', ') : undefined}
    >
      {rank !== null && <td className="text-muted">{rank}</td>}
      <td>
        {row.region ? (
          <Link to={regionAds(row.region.id)}>{row.region_label}</Link>
        ) : (
          row.region_label
        )}
        {flags.length > 0 && (
          <span className="ms-1" title={flags.join(', ')}>
            ⚠
          </span>
        )}
      </td>
      <td>{row.property_type}</td>
      <td className="text-end fw-bold">
        {formatFloat(row.months_to_buyout, 1)}
      </td>
      <td className="text-end">
        {formatFloat(row.years_to_buyout, 1)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_monthly_rent, 0)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_total_price, 0)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_monthly_rent_per_sqm, 2)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_sale_price_per_sqm, 0)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_size_rent, 0)}
      </td>
      <td className="text-end">
        {formatFloat(row.median_size_sale, 0)}
      </td>
      <td className="text-end">{row.n_rent_ads}</td>
      <td className="text-end">{row.n_sale_ads}</td>
      <td
        className="text-end"
        title={
          row.n_paired_properties
            ? `${row.n_paired_properties} same-unit pairs`
            : undefined
        }
      >
        {formatFloat(row.paired_months_to_buyout, 1)}
      </td>
    </tr>
  );
}

function CaveatNote({
  dateFrom,
  dateTo,
  minAds,
}: {
  dateFrom: string;
  dateTo: string;
  minAds: number;
}) {
  return (
    <div className="alert alert-info mt-3">
      <strong>Caveats:</strong> medians cover ads sighted between{' '}
      {dateFrom} and {dateTo}; each cell needs ≥{minAds} ads on
      both sides to rank. The rent side counts whole-unit monthly
      lets only — day/week (short-stay) and room-share ads are
      excluded. Ads parked on parent-level regions are hidden
      unless "Include residual regions" is on. Rows marked ⚠
      compare rent and sale units whose median sizes differ by
      more than 25%, or have fewer than {THIN_AD_COUNT} ads on a
      side — treat their months-to-buy as indicative only. The
      "Paired" column repeats the metric on properties carrying
      both a rent and a sale ad (shown at ≥5 pairs).
    </div>
  );
}
