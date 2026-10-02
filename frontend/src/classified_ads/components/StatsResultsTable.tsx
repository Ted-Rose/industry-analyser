import type { ReactNode } from 'react';
import type { RegionStatsRowOut } from '../api';
import { formatFloat } from '../format';

interface Props {
  results: RegionStatsRowOut[];
  /** Region cell content — a Link to children stats or region ads. */
  renderName: (row: RegionStatsRowOut) => ReactNode;
  emptyText: string;
}

/**
 * The stats table shared by the region-stats and
 * region-stats-children pages — '—' for null averages, matching the
 * templates' floatformat fallbacks.
 */
export default function StatsResultsTable({
  results,
  renderName,
  emptyText,
}: Props) {
  return (
    <div className="card filter-card">
      <div className="card-body p-0">
        <div className="table-responsive">
          <table className="table table-hover table-sm mb-0">
            <thead>
              <tr>
                <th>Region</th>
                <th className="text-end">Total ads</th>
                <th className="text-end">Properties</th>
                <th className="text-end">Avg €/m²</th>
                <th className="text-end">Avg size m²</th>
                <th className="text-end">Avg day count ad is open</th>
                <th className="text-end">Avg days on market</th>
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td
                    colSpan={7}
                    className="text-center text-muted py-4"
                  >
                    {emptyText}
                  </td>
                </tr>
              ) : (
                results.map((row) => (
                  <tr key={row.region.id}>
                    <td>{renderName(row)}</td>
                    <td className="text-end">{row.total_ads}</td>
                    <td className="text-end">{row.total_properties}</td>
                    <td className="text-end">
                      {formatFloat(row.avg_price_per_sqm, 0)}
                    </td>
                    <td className="text-end">
                      {formatFloat(row.avg_size, 1)}
                    </td>
                    <td className="text-end">
                      {formatFloat(row.avg_days_tracked, 1)}
                    </td>
                    <td className="text-end">
                      {formatFloat(row.avg_days_on_market, 1)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
