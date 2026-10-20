import { Fragment, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchReceiptsDashboard } from '../api';
import { formatDateTime, formatMoney, formatMonth } from '../format';
import { errorDetail } from '../../shared/api/errors';

/**
 * React port of the retired receipts/dashboard.html — the
 * admin-hardcoded spending report: date-range form + presets,
 * summary cards, by-month/by-store/by-category tables and the
 * all-receipts table with per-row <details> item tables. The
 * range lives in the URL as ?date_from=/&date_to= — the same
 * names the template's GET form used, so old bookmarks keep
 * filtering.
 */
export default function ReceiptsDashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
  };

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['receipts', searchParams.toString()],
    queryFn: () => fetchReceiptsDashboard(params),
  });

  // Draft-form pattern: inputs stage edits until Apply submits
  // them into the URL; data.date_from/date_to seed the effective
  // range like the template prefilled the form.
  const paramsKey = searchParams.toString();
  const [draft, setDraft] = useState({
    dateFrom: params.dateFrom ?? '',
    dateTo: params.dateTo ?? '',
  });
  useEffect(() => {
    const p = new URLSearchParams(paramsKey);
    setDraft({
      dateFrom: p.get('date_from') ?? data?.date_from ?? '',
      dateTo: p.get('date_to') ?? data?.date_to ?? '',
    });
  }, [paramsKey, data?.date_from, data?.date_to]);

  const applyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('date_from', draft.dateFrom);
    if (draft.dateTo) next.set('date_to', draft.dateTo);
    setSearchParams(next);
  };

  const monthly = data?.monthly ?? [];
  const byStore = data?.by_store ?? [];
  const categories = data?.categories ?? [];
  const receipts = data?.receipts ?? [];

  return (
    <div className="receipts-panel">
      <h1>Receipts spending</h1>

      {data?.owner_exists === false && (
        <p className="empty">
          No data — user &quot;admin&quot; does not exist.
        </p>
      )}

      {isError && (
        <div className="alert alert-danger" role="alert">
          Failed to load the dashboard — {errorDetail(error)}
        </div>
      )}

      <form className="range-form" onSubmit={applyFilters}>
        <label htmlFor="id_date_from">
          From
          <input
            type="date"
            id="id_date_from"
            name="date_from"
            value={draft.dateFrom}
            onChange={(e) =>
              setDraft((d) => ({ ...d, dateFrom: e.target.value }))
            }
          />
        </label>
        <label htmlFor="id_date_to">
          To
          <input
            type="date"
            id="id_date_to"
            name="date_to"
            value={draft.dateTo}
            onChange={(e) =>
              setDraft((d) => ({ ...d, dateTo: e.target.value }))
            }
          />
        </label>
        <button type="submit">Apply</button>
      </form>
      {data && (
        <p className="range-presets">
          <a
            href={
              `?date_from=${data.last_month_from}` +
              `&date_to=${data.last_month_to}`
            }
            onClick={(e) => {
              e.preventDefault();
              setSearchParams({
                date_from: data.last_month_from,
                date_to: data.last_month_to,
              });
            }}
          >
            Last month
          </a>{' '}
          &middot;{' '}
          {/* The template's "Last 12 months" preset was a bare
              link to the page — clearing the params re-applies
              the server-side default range. */}
          <a
            href="/receipts/"
            onClick={(e) => {
              e.preventDefault();
              setSearchParams({});
            }}
          >
            Last 12 months
          </a>{' '}
          &middot; Showing {data.date_from}&ndash;{data.date_to}
        </p>
      )}

      {data && (
        <div className="summary">
          <div className="card">
            <div className="value">
              {formatMoney(data.summary.total_spend)}
            </div>
            <div className="label">Total spend</div>
          </div>
          <div className="card">
            <div className="value">{data.summary.receipt_count}</div>
            <div className="label">Receipts</div>
          </div>
          <div className="card">
            <div className="value">{data.item_count}</div>
            <div className="label">Items</div>
          </div>
        </div>
      )}

      <h2>By month</h2>
      <table>
        <thead>
          <tr>
            <th>Month</th>
            <th className="num">Receipts</th>
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {monthly.length === 0 && !isPending ? (
            <tr>
              <td colSpan={3} className="empty">
                No data.
              </td>
            </tr>
          ) : (
            monthly.map((row) => (
              <tr key={row.month}>
                <td>{formatMonth(row.month)}</td>
                <td className="num">{row.receipt_count}</td>
                <td className="num">{formatMoney(row.total)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <h2>By store</h2>
      <table>
        <thead>
          <tr>
            <th>Store</th>
            <th className="num">Receipts</th>
            <th className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {byStore.length === 0 && !isPending ? (
            <tr>
              <td colSpan={3} className="empty">
                No data.
              </td>
            </tr>
          ) : (
            byStore.map((row) => (
              <tr key={row.store_name ?? ''}>
                <td>{row.store_name ?? '(unknown store)'}</td>
                <td className="num">{row.receipt_count}</td>
                <td className="num">{formatMoney(row.total)}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <h2>By category</h2>
      <div className="cat-table">
        <div className="cat-row cat-head">
          <span>Category</span>
          <span className="num">Items</span>
          <span className="num">Total</span>
          <span className="num">Avg / month</span>
        </div>
        {categories.length === 0 && !isPending ? (
          <p className="empty">No data.</p>
        ) : (
          categories.map((c) => (
            <details className="cat" key={c.name}>
              <summary className="cat-row">
                <span>{c.name}</span>
                <span className="num">{c.item_count}</span>
                <span className="num">{formatMoney(c.total)}</span>
                <span className="num">
                  {formatMoney(c.monthly_avg)}
                </span>
              </summary>
              <table className="cat-items">
                <thead>
                  <tr>
                    <th>Item</th>
                    <th className="num">Count</th>
                    <th className="num">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {c.top_items.map((it) => (
                    <tr key={it.raw_name}>
                      <td>{it.raw_name}</td>
                      <td className="num">{it.item_count}</td>
                      <td className="num">{formatMoney(it.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ))
        )}
      </div>

      <h2>All receipts</h2>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Store</th>
            <th>Doc. nr.</th>
            <th className="num">Total</th>
            <th>Status</th>
            <th className="num">Items</th>
          </tr>
        </thead>
        <tbody>
          {receipts.length === 0 && !isPending ? (
            <tr>
              <td colSpan={6} className="empty">
                No receipts.
              </td>
            </tr>
          ) : (
            receipts.map((r) => (
              <Fragment key={r.id}>
                <tr>
                  <td>
                    {r.purchased_at ? (
                      formatDateTime(r.purchased_at)
                    ) : (
                      <>&mdash;</>
                    )}
                  </td>
                  <td>{r.store_name ?? '(unknown)'}</td>
                  <td>{r.document_number || '—'}</td>
                  <td className="num">
                    {/* The template printed the currency code
                        here, not the € symbol. */}
                    {r.total != null
                      ? `${r.total.toFixed(2)} ${r.currency}`
                      : '—'}
                  </td>
                  <td>{r.parse_status_label}</td>
                  <td className="num">{r.item_count}</td>
                </tr>
                {r.item_count > 0 && (
                  <tr className="items-row">
                    <td colSpan={6}>
                      <details>
                        <summary>Items</summary>
                        <table>
                          <thead>
                            <tr>
                              <th>Item</th>
                              <th className="num">Qty</th>
                              <th className="num">Unit price</th>
                              <th className="num">Discount</th>
                              <th className="num">Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {r.items.map((it, idx) => (
                              <tr key={idx}>
                                <td>
                                  {it.raw_name}
                                  {it.is_fee && ' (fee)'}
                                </td>
                                <td className="num">
                                  {it.quantity} {it.unit}
                                </td>
                                <td className="num">
                                  {it.unit_price != null
                                    ? it.unit_price.toFixed(2)
                                    : '—'}
                                </td>
                                <td className="num">
                                  {it.discount.toFixed(2)}
                                </td>
                                <td className="num">
                                  {it.total.toFixed(2)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </details>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
