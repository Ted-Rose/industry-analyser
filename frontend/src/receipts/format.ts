/** Display helpers for the receipts SPA — ports of the retired
 *  dashboard.html's renders (`{{ x }} €` / `date:"F Y"` /
 *  `date:"Y-m-d H:i"`). TIME_ZONE is UTC, so datetimes format in
 *  UTC, not the browser's locale zone. */

const pad = (n: number): string => String(n).padStart(2, '0');

const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: '€',
};

const MONTH_NAMES = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];

/** `{{ x }} €` — two decimals plus the currency symbol (EUR → €;
 *  unknown codes print as-is, like the template's
 *  `{{ r.total }} {{ r.currency }}`); '—' for null. */
export function formatMoney(
  value?: number | null,
  currency = 'EUR',
): string {
  if (value == null || Number.isNaN(value)) return '—';
  return `${value.toFixed(2)} ${CURRENCY_SYMBOLS[currency] ??
    currency}`;
}

/** Django `date:"F Y"` — e.g. 'February 2026'; '—' for
 *  null/invalid. */
export function formatMonth(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return `${MONTH_NAMES[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

/** Django `date:"Y-m-d H:i"` on a UTC-aware ISO datetime —
 *  e.g. '2026-02-15 14:32'; '—' for null/invalid. */
export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-` +
    `${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:` +
    `${pad(d.getUTCMinutes())}`
  );
}
