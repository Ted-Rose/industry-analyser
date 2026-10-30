import {
  KeyboardEvent,
  MouseEvent,
  ReactNode,
  useMemo,
  useState,
} from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowDown,
  ArrowUp,
  ChevronRight,
  ChevronsUpDown,
} from 'lucide-react';
import { cx } from '../cx';
import EmptyState from './EmptyState';
import IconButton from './IconButton';
import Skeleton from './Skeleton';

export type SortDir = 'asc' | 'desc';

export interface SortState {
  id: string;
  dir: SortDir;
}

export type RowTone =
  | 'muted'
  | 'success'
  | 'warning'
  | 'danger'
  | null;

export type MobileSlot =
  | 'title'
  | 'subtitle'
  | 'meta'
  | 'badge'
  | 'hidden';

export interface Column<T> {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** 'right' implies tabular-nums. */
  align?: 'left' | 'right';
  sortable?: boolean;
  /** CSS width for the <col> element. */
  width?: string;
  /** Progressive hiding: column drops below this breakpoint. */
  hideBelow?: 'sm' | 'md' | 'lg' | 'xl';
  /** Slot in the generated mobile card; 'hidden' drops it. */
  mobile?: MobileSlot;
  /**
   * Client-sort accessor. Defaults to cell(row) when that
   * returns a string/number; otherwise the column is unsortable
   * in 'client' mode.
   */
  sortValue?: (row: T) => string | number | null | undefined;
}

export interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T) => string | number;
  /** Controlled sort state; internal state when omitted. */
  sort?: SortState;
  onSortChange?: (next: SortState) => void;
  /**
   * 'client' (default) reorders `rows` internally;
   * 'controlled' renders them as given — the caller re-sorts
   * in onSortChange.
   */
  sortMode?: 'client' | 'controlled';
  loading?: boolean;
  /** Empty-state content; defaults to a generic EmptyState. */
  empty?: ReactNode;
  /** Accessible table name — rendered as an sr-only caption. */
  caption: string;
  /** Sticky thead below the TopNav (top-14). Default true. */
  stickyHeader?: boolean;
  density?: 'compact' | 'comfortable';
  /**
   * 'cards' (default): entity lists become cards below md.
   * 'scroll': the table always renders inside a horizontal
   * scroll region — for wide numeric reports.
   */
  mobile?: 'cards' | 'scroll';
  /** mobile='scroll' only: pins column 1 while scrolling. */
  stickyFirstColumn?: boolean;
  /** Custom mobile card; defaults to the slot layout. */
  renderMobileCard?: (row: T) => ReactNode;
  /**
   * Expandable detail row — adds a leading chevron cell with
   * aria-expanded; the content lands in a colSpan row on
   * desktop and inside the card below the slots on mobile.
   */
  renderExpanded?: (row: T) => ReactNode;
  /**
   * renderExpanded only: rows where this returns false render
   * an empty chevron cell — no dead toggle on rows with
   * nothing to expand (e.g. a receipt with zero items).
   */
  hasExpanded?: (row: T) => boolean;
  /** Totals rows — rendered inside <tfoot>. */
  footer?: ReactNode;
  rowHref?: (row: T) => string;
  rowTone?: (row: T) => RowTone;
  className?: string;
}

const HIDE_BELOW: Record<
  NonNullable<Column<never>['hideBelow']>,
  string
> = {
  sm: 'hidden sm:table-cell',
  md: 'hidden md:table-cell',
  lg: 'hidden lg:table-cell',
  xl: 'hidden xl:table-cell',
};

const ROW_TONES: Record<NonNullable<RowTone>, string> = {
  muted: 'text-fg-subtle',
  success: 'bg-success-subtle',
  warning: 'bg-warning-subtle',
  danger: 'bg-danger-subtle',
};

const collator = new Intl.Collator(undefined, {
  numeric: true,
  sensitivity: 'base',
});

function cellSortValue<T>(column: Column<T>, row: T) {
  if (column.sortValue) return column.sortValue(row);
  const rendered = column.cell(row);
  if (typeof rendered === 'string' || typeof rendered === 'number') {
    return rendered;
  }
  return null;
}

function isEmptyValue(
  value: string | number | null | undefined,
): boolean {
  return value === null || value === undefined || value === '';
}

function compareValues(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): number {
  if (typeof a === 'number' && typeof b === 'number') {
    return a - b;
  }
  return collator.compare(String(a), String(b));
}

/** Clicks on interactive content must not trigger rowHref. */
function isInteractiveClick(event: MouseEvent): boolean {
  return (
    event.target instanceof Element &&
    event.target.closest(
      'a, button, input, select, textarea, [role="button"]',
    ) !== null
  );
}

/**
 * The one data table — plan §6/§6.1 `ui/DataTable`. Every prop
 * above is part of the shipped contract: client/controlled sort,
 * hideBelow, mobile cards-or-scroll, sticky header/first column,
 * expandable rows, footer, rowHref, rowTone, sr-only caption,
 * density.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  sort,
  onSortChange,
  sortMode = 'client',
  loading = false,
  empty,
  caption,
  stickyHeader = true,
  density = 'comfortable',
  mobile = 'cards',
  stickyFirstColumn = false,
  renderMobileCard,
  renderExpanded,
  hasExpanded,
  footer,
  rowHref,
  rowTone,
  className,
}: DataTableProps<T>) {
  const navigate = useNavigate();
  const [internalSort, setInternalSort] = useState<SortState>();
  const [expanded, setExpanded] = useState<Set<string | number>>(
    () => new Set(),
  );
  const effectiveSort = sort ?? internalSort;

  const sortedRows = useMemo(() => {
    if (sortMode !== 'client' || !effectiveSort) return rows;
    const column = columns.find((c) => c.id === effectiveSort.id);
    if (!column) return rows;
    const keyed = rows.map((row, index) => ({
      row,
      index,
      value: cellSortValue(column, row),
    }));
    // Empty values sort last in both directions; the index
    // tiebreak keeps the sort stable.
    const dir = effectiveSort.dir === 'desc' ? -1 : 1;
    keyed.sort((a, b) => {
      const aEmpty = isEmptyValue(a.value);
      const bEmpty = isEmptyValue(b.value);
      if (aEmpty || bEmpty) {
        return aEmpty === bEmpty
          ? a.index - b.index
          : aEmpty
            ? 1
            : -1;
      }
      return (
        dir * compareValues(a.value, b.value) || a.index - b.index
      );
    });
    return keyed.map((entry) => entry.row);
  }, [rows, columns, effectiveSort, sortMode]);

  const handleSort = (column: Column<T>) => {
    if (!column.sortable) return;
    const next: SortState =
      effectiveSort?.id === column.id && effectiveSort.dir === 'asc'
        ? { id: column.id, dir: 'desc' }
        : { id: column.id, dir: 'asc' };
    onSortChange?.(next);
    if (sort === undefined) setInternalSort(next);
  };

  const toggleExpanded = (key: string | number) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const columnCount = columns.length + (renderExpanded ? 1 : 0);
  const cellPad = density === 'compact' ? 'py-1.5' : 'py-2';
  const cellClass = (column: Column<T>) =>
    cx(
      'px-3 text-sm',
      cellPad,
      column.align === 'right' && 'text-right tabular-nums',
      column.hideBelow && HIDE_BELOW[column.hideBelow],
    );

  const goToRow = (row: T) => {
    if (rowHref) navigate(rowHref(row));
  };
  const onRowClick = (row: T) => (event: MouseEvent) => {
    if (!rowHref || isInteractiveClick(event)) return;
    // ⌘/ctrl+click opens the row in a new tab, matching real
    // anchor semantics for the link role.
    if (event.metaKey || event.ctrlKey) {
      window.open(rowHref(row), '_blank', 'noopener');
      return;
    }
    goToRow(row);
  };
  const onRowAuxClick = (row: T) => (event: MouseEvent) => {
    if (
      !rowHref ||
      event.button !== 1 ||
      isInteractiveClick(event)
    ) {
      return;
    }
    // Middle-click also opens in a new tab (and suppresses the
    // default autoscroll).
    event.preventDefault();
    window.open(rowHref(row), '_blank', 'noopener');
  };
  const onRowKeyDown = (row: T) => (event: KeyboardEvent) => {
    if (!rowHref || event.target !== event.currentTarget) return;
    if (event.key === 'Enter') {
      event.preventDefault();
      goToRow(row);
    }
  };

  const emptyContent = empty ?? (
    <EmptyState title="No results found." />
  );

  const renderHeaderCell = (column: Column<T>, index: number) => {
    const sorted = effectiveSort?.id === column.id;
    const icon = sorted ? (
      effectiveSort.dir === 'asc' ? (
        <ArrowUp className="size-3.5" aria-hidden="true" />
      ) : (
        <ArrowDown className="size-3.5" aria-hidden="true" />
      )
    ) : (
      <ChevronsUpDown
        className="size-3.5 text-fg-subtle"
        aria-hidden="true"
      />
    );
    return (
      <th
        key={column.id}
        scope="col"
        aria-sort={
          sorted
            ? effectiveSort.dir === 'asc'
              ? 'ascending'
              : 'descending'
            : undefined
        }
        className={cx(
          'px-3 py-2 text-left text-xs font-medium uppercase ' +
            'tracking-wide text-fg-muted',
          column.align === 'right' && 'text-right',
          column.hideBelow && HIDE_BELOW[column.hideBelow],
          // A left-pinned header cell needs `sticky` and an
          // opaque bg even when stickyHeader is off.
          (stickyHeader || (stickyFirstColumn && index === 0)) &&
            'sticky bg-surface-2',
          stickyHeader && 'top-14 z-10',
          stickyFirstColumn &&
            index === 0 &&
            // With a leading chevron column (renderExpanded) the
            // pinned first data column sits at left-10 — the
            // chevron's w-10 — instead of covering it at left-0.
            (renderExpanded ? 'left-10 z-20' : 'left-0 z-20'),
        )}
      >
        {column.sortable ? (
          <button
            type="button"
            onClick={() => handleSort(column)}
            className={cx(
              '-mx-1 inline-flex items-center gap-1 rounded px-1 ' +
                'py-0.5 hover:text-fg',
              column.align === 'right' && 'flex-row-reverse',
            )}
          >
            {column.header}
            {icon}
          </button>
        ) : (
          column.header
        )}
      </th>
    );
  };

  const renderRow = (row: T) => {
    const key = getRowKey(row);
    const isOpen = expanded.has(key);
    const canExpand = hasExpanded?.(row) ?? true;
    const tone = rowTone?.(row) ?? null;
    return [
      <tr
        key={key}
        role={rowHref ? 'link' : undefined}
        onClick={onRowClick(row)}
        onAuxClick={onRowAuxClick(row)}
        onKeyDown={onRowKeyDown(row)}
        tabIndex={rowHref ? 0 : undefined}
        className={cx(
          'border-b border-border last:border-0 ' +
            'transition-colors motion-safe:duration-120 ease-ia ' +
            'hover:bg-surface-2',
          rowHref && 'cursor-pointer',
          tone && ROW_TONES[tone],
        )}
      >
        {renderExpanded && (
          <td
            className={cx(
              'w-10 pl-2 pr-0',
              cellPad,
              stickyFirstColumn &&
                'sticky left-0 z-[5] bg-surface',
            )}
          >
            {canExpand && (
              <IconButton
                size="sm"
                label={isOpen ? 'Collapse row' : 'Expand row'}
                aria-expanded={isOpen}
                icon={
                  <ChevronRight
                    className={cx(
                      'transition-transform ' +
                        'motion-safe:duration-180 ease-ia',
                      isOpen && 'rotate-90',
                    )}
                  />
                }
                onClick={() => toggleExpanded(key)}
              />
            )}
          </td>
        )}
        {columns.map((column, index) => (
          <td
            key={column.id}
            className={cx(
              cellClass(column),
              stickyFirstColumn &&
                index === 0 &&
                cx(
                  'sticky z-[5] bg-surface',
                  renderExpanded ? 'left-10' : 'left-0',
                ),
            )}
          >
            {column.cell(row)}
          </td>
        ))}
      </tr>,
      isOpen && renderExpanded && canExpand ? (
        <tr key={`${String(key)}-expanded`} className="border-b
          border-border">
          <td colSpan={columnCount} className="bg-surface-2 px-4 py-3">
            {renderExpanded(row)}
          </td>
        </tr>
      ) : null,
    ];
  };

  const renderMobileCardContent = (row: T) => {
    if (renderMobileCard) return renderMobileCard(row);
    const bySlot = (slot: MobileSlot) =>
      columns.filter((c) => c.mobile === slot);
    const slotted = new Set(
      bySlot('title')
        .concat(bySlot('subtitle'), bySlot('meta'), bySlot('badge'))
        .map((c) => c.id),
    );
    const details = columns.filter(
      (c) => !slotted.has(c.id) && c.mobile !== 'hidden',
    );
    const key = getRowKey(row);
    const isOpen = expanded.has(key);
    const canExpand = hasExpanded?.(row) ?? true;
    return (
      <>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 font-medium text-fg">
            {bySlot('title').map((c) => (
              <span key={c.id}>{c.cell(row)}</span>
            ))}
          </div>
          {bySlot('badge').map((c) => (
            <span key={c.id} className="shrink-0">
              {c.cell(row)}
            </span>
          ))}
        </div>
        {bySlot('subtitle').map((c) => (
          <div key={c.id} className="mt-1 text-sm text-fg-muted">
            {c.cell(row)}
          </div>
        ))}
        {bySlot('meta').map((c) => (
          <div key={c.id} className="mt-1 text-xs text-fg-subtle">
            {c.cell(row)}
          </div>
        ))}
        {details.length > 0 && (
          <dl className="mt-2 space-y-1">
            {details.map((c) => (
              <div
                key={c.id}
                className="flex items-baseline justify-between gap-3"
              >
                <dt className="shrink-0 text-xs text-fg-subtle">
                  {c.header}
                </dt>
                <dd
                  className={cx(
                    'min-w-0 text-right text-sm text-fg',
                    c.align === 'right' && 'tabular-nums',
                  )}
                >
                  {c.cell(row)}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {renderExpanded && canExpand && (
          <div className="mt-2">
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => toggleExpanded(key)}
              className="inline-flex items-center gap-1 rounded-md
                px-2 py-2.5 text-sm font-medium text-accent-text
                hover:bg-accent-subtle"
            >
              <ChevronRight
                className={cx(
                  'size-4 transition-transform ' +
                    'motion-safe:duration-180 ease-ia',
                  isOpen && 'rotate-90',
                )}
                aria-hidden="true"
              />
              Details
            </button>
            {isOpen && (
              <div className="mt-2 border-t border-border pt-2">
                {renderExpanded(row)}
              </div>
            )}
          </div>
        )}
      </>
    );
  };

  const tableEl = (
    <table className="w-full border-collapse text-left">
      <caption className="sr-only">{caption}</caption>
      <colgroup>
        {renderExpanded && <col className="w-10" />}
        {columns.map((column) => (
          <col
            key={column.id}
            style={column.width ? { width: column.width } : undefined}
          />
        ))}
      </colgroup>
      <thead>
        <tr className="border-b border-border">
          {renderExpanded && (
            <th
              scope="col"
              className={cx(
                'w-10 px-2 py-2',
                (stickyHeader || stickyFirstColumn) &&
                  'sticky bg-surface-2',
                stickyHeader && 'top-14',
                // With stickyFirstColumn the chevron column pins
                // at the left edge and the first data column pins
                // beside it at left-10 — z-30 keeps this header
                // above that column's z-20 header cell.
                stickyFirstColumn
                  ? 'left-0 z-30'
                  : stickyHeader && 'z-10',
              )}
            >
              <span className="sr-only">Expand</span>
            </th>
          )}
          {columns.map(renderHeaderCell)}
        </tr>
      </thead>
      <tbody aria-busy={loading || undefined}>
        {loading
          ? Array.from({ length: 5 }, (_, index) => (
              <tr key={index} className="border-b border-border">
                {renderExpanded && (
                  <td className={cx('px-3', cellPad)}>
                    <Skeleton className="h-4 w-6" />
                  </td>
                )}
                {columns.map((column) => (
                  <td key={column.id} className={cellClass(column)}>
                    <Skeleton className="h-4 w-full max-w-32" />
                  </td>
                ))}
              </tr>
            ))
          : sortedRows.map(renderRow)}
        {!loading && sortedRows.length === 0 && (
          <tr>
            <td colSpan={columnCount} className="px-3 py-8">
              {emptyContent}
            </td>
          </tr>
        )}
      </tbody>
      {footer && <tfoot>{footer}</tfoot>}
    </table>
  );

  const mobileCards = mobile === 'cards' && (
    <ul className="space-y-3 md:hidden" aria-busy={loading || undefined}>
      {loading
        ? Array.from({ length: 3 }, (_, index) => (
            <li
              key={index}
              className="rounded-lg border border-border
                bg-surface p-4"
            >
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="mt-2 h-4 w-full" />
              <Skeleton className="mt-1 h-4 w-1/2" />
            </li>
          ))
        : sortedRows.map((row) => {
            const key = getRowKey(row);
            const tone = rowTone?.(row) ?? null;
            return (
              <li
                key={key}
                role={rowHref ? 'link' : undefined}
                onClick={onRowClick(row)}
                onAuxClick={onRowAuxClick(row)}
                onKeyDown={onRowKeyDown(row)}
                tabIndex={rowHref ? 0 : undefined}
                className={cx(
                  'rounded-lg border border-border bg-surface p-4',
                  rowHref && 'cursor-pointer',
                  tone && ROW_TONES[tone],
                )}
              >
                {renderMobileCardContent(row)}
              </li>
            );
          })}
      {!loading && sortedRows.length === 0 && <li>{emptyContent}</li>}
    </ul>
  );

  return (
    <div className={className}>
      <div
        className={cx(
          mobile === 'cards' && 'hidden md:block',
          mobile === 'scroll' &&
            'overflow-x-auto rounded-lg border border-border',
        )}
      >
        {tableEl}
      </div>
      {mobileCards}
    </div>
  );
}

export default DataTable;
