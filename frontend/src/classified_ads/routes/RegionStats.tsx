import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionStats,
  type Kind,
  type RegionStatsRowOut,
} from '../api';
import { errorDetail } from '../../shared/api/errors';
import StatsResultsTable from '../components/StatsResultsTable';
import { kindUrls } from '../urls';

interface Draft {
  dateFrom: string;
  dateTo: string;
  dealType: string;
  regions: Set<string>;
}

/**
 * React port of region_stats.html / house_region_stats.html —
 * date range + deal type + a checkbox list of parent regions;
 * results render only once at least one region is checked (the old
 * `{% if results is not None %}` gate). Filters live in the URL.
 */
export default function RegionStats({ kind }: { kind: Kind }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    dealType: searchParams.get('deal_type'),
    regions: searchParams.getAll('regions'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'region-stats',
      kind,
      searchParams.toString(),
    ],
    queryFn: () => fetchRegionStats(kind, params),
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    dateFrom: params.dateFrom ?? '',
    dateTo: params.dateTo ?? '',
    dealType: params.dealType ?? '',
    regions: new Set(params.regions),
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      dateFrom: p.get('date_from') ?? '',
      dateTo: p.get('date_to') ?? '',
      dealType: p.get('deal_type') ?? '',
      regions: new Set(p.getAll('regions')),
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('date_from', draft.dateFrom);
    if (draft.dateTo) next.set('date_to', draft.dateTo);
    if (draft.dealType) next.set('deal_type', draft.dealType);
    [...draft.regions].forEach((id) => next.append('regions', id));
    setSearchParams(next);
  };

  const urls = kindUrls(kind);
  const toggleRegion = (id: string, on: boolean) => {
    setDraft((d) => {
      const regions = new Set(d.regions);
      if (on) regions.add(id);
      else regions.delete(id);
      return { ...d, regions };
    });
  };

  return (
    <div className="container-fluid py-4">
      <Link to={urls.config} className="back-link">
        ← Back to Region Configuration
      </Link>
      <h2 className="mb-4">
        {kind === 'apartment' ? 'Apartment' : 'House'} Region Stats
      </h2>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form onSubmit={applyFilters}>
            <div className="row align-items-end mb-2">
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
            </div>

            <label className="filter-label d-block mb-1">
              Parent regions
            </label>
            <div className="region-checkbox-list border rounded p-2 mb-3">
              {data && data.parent_regions.length === 0 && (
                <p className="text-muted mb-0">
                  No parent regions found.
                </p>
              )}
              {data?.parent_regions.map((region) => (
                <div className="region-checkbox-item" key={region.id}>
                  <label className="mb-0">
                    <input
                      type="checkbox"
                      checked={draft.regions.has(String(region.id))}
                      onChange={(e) =>
                        toggleRegion(String(region.id), e.target.checked)
                      }
                    />{' '}
                    {region.name}
                  </label>
                </div>
              ))}
            </div>

            <button type="submit" className="btn btn-primary btn-sm">
              Fetch
            </button>
          </form>
        </div>
      </div>

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load stats — {errorDetail(error)}
        </div>
      )}

      {/* Results — only once at least one region is selected */}
      {data && data.results !== null && (
        <>
          <StatsResultsTable
            results={data.results}
            renderName={(row: RegionStatsRowOut) => (
              <Link
                to={`${urls.statsChildren(row.region.id)}?date_from=${data.date_from}&date_to=${data.date_to}&deal_type=${data.deal_type}`}
              >
                {row.region.name}
              </Link>
            )}
            emptyText="No regions selected."
          />
          {!data.deal_type && <NoDealTypeNote />}
        </>
      )}
      {isPending && <p className="text-muted">Loading…</p>}
    </div>
  );
}

/** The alert shown when no deal type is picked — verbatim copy from
 *  the templates. */
export function NoDealTypeNote() {
  return (
    <div className="alert alert-info mt-3">
      <strong>Note:</strong> Average values (€/m², size, days tracked)
      are only calculated when a specific deal type (Rent or Sell) is
      selected. Please select a deal type from the filter above to see
      these statistics.
    </div>
  );
}
