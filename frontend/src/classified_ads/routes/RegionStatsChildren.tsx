import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionStatsChildren,
  type Kind,
  type RegionStatsRowOut,
} from '../api';
import { errorDetail } from '../../shared/api/errors';
import StatsResultsTable from '../components/StatsResultsTable';
import { NoDealTypeNote } from './RegionStats';
import { kindUrls } from '../urls';

interface Draft {
  dateFrom: string;
  dateTo: string;
  dealType: string;
}

/**
 * React port of region_stats_children.html /
 * house_region_stats_children.html — per-sub-region stats for one
 * parent region; rows link through to that child's ads list.
 * date_from/date_to/deal_type live in the URL.
 */
export default function RegionStatsChildren({ kind }: { kind: Kind }) {
  const { regionId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    dealType: searchParams.get('deal_type'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'region-stats-children',
      kind,
      regionId,
      searchParams.toString(),
    ],
    queryFn: () =>
      fetchRegionStatsChildren(kind, regionId ?? '', params),
    enabled: !!regionId,
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    dateFrom: params.dateFrom ?? '',
    dateTo: params.dateTo ?? '',
    dealType: params.dealType ?? '',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      dateFrom: p.get('date_from') ?? '',
      dateTo: p.get('date_to') ?? '',
      dealType: p.get('deal_type') ?? '',
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('date_from', draft.dateFrom);
    if (draft.dateTo) next.set('date_to', draft.dateTo);
    if (draft.dealType) next.set('deal_type', draft.dealType);
    setSearchParams(next);
  };

  const urls = kindUrls(kind);
  const parent = data?.parent_region;

  return (
    <div className="container-fluid py-4">
      {parent && data && (
        <Link
          to={`${urls.stats}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}&regions=${parent.id}`}
          className="back-link"
        >
          ← Back to parent regions
        </Link>
      )}
      <h2 className="mb-4">
        {parent ? `${parent.name} — Sub-regions` : 'Sub-regions'}
      </h2>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form onSubmit={applyFilters}>
            <div className="row align-items-end">
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_date_from">
                  From
                </label>
                <input
                  type="date"
                  id="id_date_from"
                  className="form-control form-control-sm"
                  value={draft.dateFrom}
                  onChange={(e) =>
                    setDraft((d) => ({
                      ...d,
                      dateFrom: e.target.value,
                    }))
                  }
                />
              </div>
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_date_to">
                  To
                </label>
                <input
                  type="date"
                  id="id_date_to"
                  className="form-control form-control-sm"
                  value={draft.dateTo}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, dateTo: e.target.value }))
                  }
                />
              </div>
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_deal_type">
                  Deal type
                </label>
                <select
                  id="id_deal_type"
                  className="form-control form-control-sm"
                  value={draft.dealType}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, dealType: e.target.value }))
                  }
                >
                  <option value="">All</option>
                  <option value="RENT">Rent</option>
                  <option value="SELL">Sell</option>
                </select>
              </div>
              <div className="col-md-1 mb-2 d-flex align-items-end">
                <button
                  type="submit"
                  className="btn btn-primary btn-sm w-100"
                >
                  Fetch
                </button>
              </div>
            </div>
          </form>
        </div>
      </div>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load stats — {errorDetail(error)}
        </div>
      )}

      {data && (
        <>
          <StatsResultsTable
            results={data.results}
            renderName={(row: RegionStatsRowOut) => (
              <Link
                to={`${urls.regionAds(row.region.id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`}
                className="region-link"
              >
                {row.region.name}
              </Link>
            )}
            emptyText="No sub-regions found."
          />
          {!data.deal_type && <NoDealTypeNote />}
        </>
      )}
      {isPending && <p className="text-muted">Loading…</p>}
    </div>
  );
}
