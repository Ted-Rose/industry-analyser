import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchDailySightings } from '../api';
import { formatDateWithWeekday } from '../format';
import { errorDetail } from '../../shared/api/errors';

interface Draft {
  dateFrom: string;
  dateTo: string;
  region: string;
  order: string;
}

/**
 * React port of daily_sightings_report.html — per-day sighting counts
 * for the four ad tables inside a date window, optionally restricted
 * to a region subtree (parent + sub-region <optgroup> select) and an
 * asc/desc order toggle. Filters live in the URL; the summary cards
 * are computed from daily_data (rounded to whole numbers, matching
 * the template's widthratio math).
 */
export default function DailySightings() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
    order: searchParams.get('order'),
    region: searchParams.get('region'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: [
      'classified_ads',
      'sightings',
      searchParams.toString(),
    ],
    queryFn: () => fetchDailySightings(params),
  });

  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState<Draft>({
    dateFrom: params.dateFrom ?? '',
    dateTo: params.dateTo ?? '',
    region: params.region ?? '',
    order: params.order ?? 'desc',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      dateFrom: p.get('date_from') ?? '',
      dateTo: p.get('date_to') ?? '',
      region: p.get('region') ?? '',
      order: p.get('order') ?? 'desc',
    });
  }, [paramsKey]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('date_from', draft.dateFrom);
    if (draft.dateTo) next.set('date_to', draft.dateTo);
    if (draft.region) next.set('region', draft.region);
    if (draft.order) next.set('order', draft.order);
    setSearchParams(next);
  };

  const daily = data?.daily_data ?? [];
  const dayCount = daily.length;
  const aptAvg = dayCount
    ? Math.round(
        daily.reduce((s, d) => s + d.apartment_total, 0) / dayCount,
      )
    : 0;
  const houseAvg = dayCount
    ? Math.round(
        daily.reduce((s, d) => s + d.house_total, 0) / dayCount,
      )
    : 0;
  const grandSum = daily.reduce((s, d) => s + d.grand_total, 0);

  return (
    <div className="container-fluid py-4">
      <h2 className="mb-4">Daily Sightings Report</h2>

      {/* Filters */}
      <div className="card filter-card mb-4">
        <div className="card-body">
          <form onSubmit={applyFilters}>
            <div className="row align-items-end">
              <div className="col-md-3 mb-2">
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
              <div className="col-md-3 mb-2">
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
                <label className="filter-label" htmlFor="id_region">
                  Region
                </label>
                <select
                  id="id_region"
                  className="form-control form-control-sm"
                  value={draft.region}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, region: e.target.value }))
                  }
                >
                  <option value="">All Regions</option>
                  {data?.regions.map((region) => (
                    <optgroup key={region.id} label={region.name}>
                      <option value={region.id}>{region.name}</option>
                      {region.sub_regions.map((sub) => (
                        <option key={sub.id} value={sub.id}>
                          &nbsp;&nbsp;{sub.name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
              <div className="col-md-2 mb-2">
                <label className="filter-label" htmlFor="id_order">
                  Order
                </label>
                <select
                  id="id_order"
                  className="form-control form-control-sm"
                  value={draft.order}
                  onChange={(e) =>
                    setDraft((d) => ({ ...d, order: e.target.value }))
                  }
                >
                  <option value="asc">Oldest First</option>
                  <option value="desc">Newest First</option>
                </select>
              </div>
              <div className="col-md-2 mb-2">
                <button
                  type="submit"
                  className="btn btn-primary btn-sm"
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
          Failed to load the report — {errorDetail(error)}
        </div>
      )}

      {/* Summary cards */}
      {daily.length > 0 && (
        <div className="row mb-4">
          <div className="col-md-3">
            <div className="card summary-card">
              <div className="card-body text-center">
                <div className="summary-value">{dayCount}</div>
                <div className="summary-label">Days with Data</div>
              </div>
            </div>
          </div>
          <div className="col-md-3">
            <div className="card summary-card">
              <div className="card-body text-center">
                <div className="summary-value">{aptAvg}</div>
                <div className="summary-label">Avg Apartments/Day</div>
              </div>
            </div>
          </div>
          <div className="col-md-3">
            <div className="card summary-card">
              <div className="card-body text-center">
                <div className="summary-value">{houseAvg}</div>
                <div className="summary-label">Avg Houses/Day</div>
              </div>
            </div>
          </div>
          <div className="col-md-3">
            <div className="card summary-card">
              <div className="card-body text-center">
                <div className="summary-value">{grandSum}</div>
                <div className="summary-label">Total Sightings</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Results table */}
      <div className="card filter-card">
        <div className="card-body p-0">
          <div className="table-responsive">
            <table className="table table-hover table-sm mb-0">
              <thead>
                <tr>
                  <th>Date</th>
                  <th className="text-end">Apt. Rent</th>
                  <th className="text-end">Apt. Sale</th>
                  <th className="text-end">Apt. Total</th>
                  <th className="text-end">House Rent</th>
                  <th className="text-end">House Sale</th>
                  <th className="text-end">House Total</th>
                  <th className="text-end">Grand Total</th>
                </tr>
              </thead>
              <tbody>
                {daily.length === 0 && !isPending ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="text-center text-muted py-4"
                    >
                      No sightings found for the selected date range.
                    </td>
                  </tr>
                ) : (
                  daily.map((day) => (
                    <tr key={day.date}>
                      <td>{formatDateWithWeekday(day.date)}</td>
                      <td className="text-end">{day.apartment_rent}</td>
                      <td className="text-end">{day.apartment_sale}</td>
                      <td className="text-end">
                        <strong>{day.apartment_total}</strong>
                      </td>
                      <td className="text-end">{day.house_rent}</td>
                      <td className="text-end">{day.house_sale}</td>
                      <td className="text-end">
                        <strong>{day.house_total}</strong>
                      </td>
                      <td className="text-end">
                        <strong>{day.grand_total}</strong>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
