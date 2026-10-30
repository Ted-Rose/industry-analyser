import { ReactNode, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  keepPreviousData,
  useQuery,
} from '@tanstack/react-query';
import { fetchReceiptsDashboard } from '../api';
import type {
  CategoryOut,
  MonthlyRowOut,
  ReceiptItemOut,
  ReceiptRowOut,
  StoreRowOut,
  TopItemOut,
} from '../api';
import {
  formatDateTime,
  formatMoney,
  formatMonth,
} from '../format';
import { errorDetail } from '../../shared/api/errors';
import { cx } from '../../shared/cx';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Badge, { type BadgeTone } from '../../shared/ui/Badge';
import Button from '../../shared/ui/Button';
import Card from '../../shared/ui/Card';
import DataTable, {
  type Column,
} from '../../shared/ui/DataTable';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState from '../../shared/ui/ErrorState';
import Field from '../../shared/ui/Field';
import FilterBar from '../../shared/ui/FilterBar';
import Input from '../../shared/ui/Input';
import { LoadingState } from '../../shared/ui/Skeleton';
import StatCard, {
  StatGrid,
} from '../../shared/ui/StatCard';
import { pushToast } from '../../shared/toasts';

const MUTED = 'text-fg-subtle';

/** Inner-table cells inside an expanded DataTable row. */
const EXPAND_TH =
  'px-3 py-1.5 text-left text-xs font-medium uppercase ' +
  'tracking-wide text-fg-muted';
const EXPAND_TD = 'px-3 py-1.5 text-sm';

/** parse_status_label → Badge tone. */
const STATUS_TONES: Record<string, BadgeTone> = {
  Parsed: 'success',
  'Total mismatch': 'warning',
  'Parse error': 'danger',
};

const MONTH_COLUMNS: Column<MonthlyRowOut>[] = [
  {
    id: 'month',
    header: 'Month',
    sortable: true,
    sortValue: (row) => row.month,
    mobile: 'title',
    cell: (row) => formatMonth(row.month),
  },
  {
    id: 'receipts',
    header: 'Receipts',
    align: 'right',
    sortable: true,
    cell: (row) => row.receipt_count,
  },
  {
    id: 'total',
    header: 'Total',
    align: 'right',
    sortable: true,
    sortValue: (row) => row.total,
    cell: (row) => formatMoney(row.total),
  },
];

const STORE_COLUMNS: Column<StoreRowOut>[] = [
  {
    id: 'store',
    header: 'Store',
    sortable: true,
    sortValue: (row) => row.store_name ?? '',
    mobile: 'title',
    cell: (row) => row.store_name ?? '(unknown store)',
  },
  {
    id: 'receipts',
    header: 'Receipts',
    align: 'right',
    sortable: true,
    cell: (row) => row.receipt_count,
  },
  {
    id: 'total',
    header: 'Total',
    align: 'right',
    sortable: true,
    sortValue: (row) => row.total,
    cell: (row) => formatMoney(row.total),
  },
];

const CATEGORY_COLUMNS: Column<CategoryOut>[] = [
  {
    id: 'name',
    header: 'Category',
    sortable: true,
    mobile: 'title',
    cell: (row) => row.name,
  },
  {
    id: 'items',
    header: 'Items',
    align: 'right',
    sortable: true,
    cell: (row) => row.item_count,
  },
  {
    id: 'total',
    header: 'Total',
    align: 'right',
    sortable: true,
    sortValue: (row) => row.total,
    cell: (row) => formatMoney(row.total),
  },
  {
    id: 'avg',
    header: 'Avg / month',
    align: 'right',
    sortable: true,
    sortValue: (row) => row.monthly_avg,
    cell: (row) => formatMoney(row.monthly_avg),
  },
];

const RECEIPT_COLUMNS: Column<ReceiptRowOut>[] = [
  {
    id: 'date',
    header: 'Date',
    sortable: true,
    sortValue: (row) => row.purchased_at ?? '',
    mobile: 'subtitle',
    cell: (row) =>
      row.purchased_at ? (
        formatDateTime(row.purchased_at)
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
  {
    id: 'store',
    header: 'Store',
    sortable: true,
    sortValue: (row) => row.store_name ?? '',
    mobile: 'title',
    cell: (row) => row.store_name ?? '(unknown)',
  },
  {
    id: 'doc',
    header: 'Doc. nr.',
    sortable: true,
    sortValue: (row) => row.document_number,
    mobile: 'meta',
    cell: (row) =>
      row.document_number || (
        <span className={MUTED}>&mdash;</span>
      ),
  },
  {
    id: 'total',
    header: 'Total',
    align: 'right',
    sortable: true,
    sortValue: (row) => row.total,
    cell: (row) =>
      // The template printed the currency code here, not the €
      // symbol — '5.98 EUR', kept verbatim.
      row.total != null ? (
        `${row.total.toFixed(2)} ${row.currency}`
      ) : (
        <span className={MUTED}>&mdash;</span>
      ),
  },
  {
    id: 'status',
    header: 'Status',
    mobile: 'badge',
    cell: (row) => (
      <Badge tone={STATUS_TONES[row.parse_status_label]}>
        {row.parse_status_label}
      </Badge>
    ),
  },
  {
    id: 'items',
    header: 'Items',
    align: 'right',
    sortable: true,
    cell: (row) => row.item_count,
  },
];

/** h2 + Card section shell — §7 multi-section report recipe. */
function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section>
      <h2 className="mb-3 text-xl font-semibold text-fg">
        {title}
      </h2>
      <Card padding="none" className="overflow-hidden">
        {children}
      </Card>
    </section>
  );
}

/** Muted one-liner standing in for an empty section table. */
function EmptyLine({ text }: { text: string }) {
  return (
    <p className="px-4 py-6 text-sm italic text-fg-subtle">
      {text}
    </p>
  );
}

/** A category's top-items table (expanded row content). */
function TopItemsTable({ items }: { items: TopItemOut[] }) {
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">Top items</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className={EXPAND_TH}>
            Item
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Count
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Total
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((it) => (
          <tr
            key={it.raw_name}
            className="border-b border-border last:border-0"
          >
            <td className={EXPAND_TD}>{it.raw_name}</td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {it.item_count}
            </td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {formatMoney(it.total)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** A receipt's line items (expanded row content). */
function ReceiptItemsTable({
  items,
}: {
  items: ReceiptItemOut[];
}) {
  return (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">Receipt items</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className={EXPAND_TH}>
            Item
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Qty
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Unit price
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Discount
          </th>
          <th
            scope="col"
            className={cx(EXPAND_TH, 'text-right')}
          >
            Total
          </th>
        </tr>
      </thead>
      <tbody>
        {items.map((it, idx) => (
          <tr
            key={idx}
            className="border-b border-border last:border-0"
          >
            <td className={EXPAND_TD}>
              {it.raw_name}
              {it.is_fee && ' (fee)'}
            </td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {it.quantity} {it.unit}
            </td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {it.unit_price != null
                ? it.unit_price.toFixed(2)
                : '—'}
            </td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {it.discount.toFixed(2)}
            </td>
            <td
              className={cx(
                EXPAND_TD,
                'text-right tabular-nums',
              )}
            >
              {it.total.toFixed(2)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * React port of the retired receipts/dashboard.html — the
 * admin-hardcoded spending report: date-range form + presets,
 * summary cards, by-month/by-store/by-category tables and the
 * all-receipts table with expandable per-row item tables — now
 * on the shared component kit (plan §9.5). The range lives in
 * the URL as ?date_from=/&date_to= — the same names the
 * template's GET form used, so old bookmarks keep filtering.
 */
export default function ReceiptsDashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = {
    dateFrom: searchParams.get('date_from'),
    dateTo: searchParams.get('date_to'),
  };

  const {
    data,
    isPending,
    isFetching,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['receipts', searchParams.toString()],
    queryFn: () => fetchReceiptsDashboard(params),
    // A range change keeps the previous window's rows on
    // screen while the new one loads — the opacity dim below
    // is the only "loading" signal a refetch needs.
    placeholderData: keepPreviousData,
  });

  // Query failures surface both inline (ErrorState) and as a
  // toast — a failed background refetch must still be visible
  // while old rows stay on screen. The ref dedupes StrictMode's
  // double-effect and repeat failures of the same error.
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(
      `Failed to load the dashboard — ${errorDetail(error)}`,
      'danger',
    );
  }, [isError, error]);

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

  const applyFilters = () => {
    const next = new URLSearchParams();
    if (draft.dateFrom) next.set('date_from', draft.dateFrom);
    if (draft.dateTo) next.set('date_to', draft.dateTo);
    setSearchParams(next);
  };

  const monthly = data?.monthly ?? [];
  const byStore = data?.by_store ?? [];
  const categories = data?.categories ?? [];
  const receipts = data?.receipts ?? [];

  // Presets are one-shot actions, not a persistent selection —
  // plain Buttons in the FilterBar actions slot (plan §8.2).
  const presetActions = data ? (
    <>
      <Button
        variant="secondary"
        onClick={() =>
          setSearchParams({
            date_from: data.last_month_from,
            date_to: data.last_month_to,
          })
        }
      >
        Last month
      </Button>
      {/* The template's "Last 12 months" preset was a bare link
          to the page — clearing the params re-applies the
          server-side default range. */}
      <Button
        variant="secondary"
        onClick={() => setSearchParams({})}
      >
        Last 12 months
      </Button>
    </>
  ) : undefined;

  return (
    <PageContainer width="page">
      <PageHeader
        title="Receipts spending"
        description={
          'Spending report over the receipts collected ' +
          'for the admin user.'
        }
      />
      <FilterBar onSubmit={applyFilters} actions={presetActions}>
        <Field label="From" htmlFor="id_date_from">
          <Input
            type="date"
            id="id_date_from"
            name="date_from"
            value={draft.dateFrom}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                dateFrom: e.target.value,
              }))
            }
          />
        </Field>
        <Field label="To" htmlFor="id_date_to">
          <Input
            type="date"
            id="id_date_to"
            name="date_to"
            value={draft.dateTo}
            onChange={(e) =>
              setDraft((d) => ({
                ...d,
                dateTo: e.target.value,
              }))
            }
          />
        </Field>
      </FilterBar>
      {isError && !data ? (
        <ErrorState
          title="Failed to load the dashboard"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
          className="mt-6"
        />
      ) : isPending || !data ? (
        <LoadingState variant="stats" className="mt-6" />
      ) : (
        <div
          aria-busy={isFetching}
          className={cx(
            'mt-6 space-y-6 transition-opacity ' +
              'motion-safe:duration-180 ease-ia',
            isFetching && 'opacity-60',
          )}
        >
          <p className="text-sm text-fg-muted tabular-nums">
            Showing {data.date_from}&ndash;{data.date_to}
          </p>

          {data.owner_exists === false && (
            <EmptyState
              title={
                'No data — user "admin" does not exist.'
              }
            />
          )}

          <div data-testid="summary">
            <StatGrid>
              <StatCard
                label="Total spend"
                value={formatMoney(data.summary.total_spend)}
              />
              <StatCard
                label="Receipts"
                value={data.summary.receipt_count}
              />
              <StatCard
                label="Items"
                value={data.item_count}
              />
            </StatGrid>
          </div>

          <Section title="By month">
            {monthly.length === 0 ? (
              <EmptyLine text="No data." />
            ) : (
              <DataTable
                columns={MONTH_COLUMNS}
                rows={monthly}
                getRowKey={(row) => row.month}
                caption="Spending by month"
                className="max-md:p-3"
              />
            )}
          </Section>

          <Section title="By store">
            {byStore.length === 0 ? (
              <EmptyLine text="No data." />
            ) : (
              <DataTable
                columns={STORE_COLUMNS}
                rows={byStore}
                getRowKey={(row) => row.store_name ?? ''}
                caption="Spending by store"
                className="max-md:p-3"
              />
            )}
          </Section>

          <Section title="By category">
            {categories.length === 0 ? (
              <EmptyLine text="No data." />
            ) : (
              <DataTable
                columns={CATEGORY_COLUMNS}
                rows={categories}
                getRowKey={(row) => row.name}
                caption="Spending by category"
                renderExpanded={(row) =>
                  row.top_items.length > 0 ? (
                    <TopItemsTable items={row.top_items} />
                  ) : (
                    <EmptyLine text="No items recorded." />
                  )
                }
                className="max-md:p-3"
              />
            )}
          </Section>

          <Section title="All receipts">
            {receipts.length === 0 ? (
              <EmptyLine text="No receipts." />
            ) : (
              <DataTable
                columns={RECEIPT_COLUMNS}
                rows={receipts}
                getRowKey={(row) => row.id}
                caption="All receipts"
                renderExpanded={(row) =>
                  row.item_count > 0 ? (
                    <ReceiptItemsTable items={row.items} />
                  ) : (
                    <EmptyLine text="No items recorded." />
                  )
                }
                className="max-md:p-3"
              />
            )}
          </Section>
        </div>
      )}
    </PageContainer>
  );
}
