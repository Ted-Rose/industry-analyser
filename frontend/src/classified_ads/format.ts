/** Display helpers ported from the retired classified_ads templates. */

/** Parse 'YYYY-MM-DD' (or ISO datetime) into a local Date — `new
 * Date('2024-05-01')` is UTC midnight, which shifts a day back for
 * users behind UTC; Django's template rendering never shifted. */
function parseDate(iso: string): Date | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return null;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}

/** Django `date:"d.m.Y"` — e.g. 06.01.2025; '—' for null/invalid. */
export function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = parseDate(iso);
  if (!d) return '—';
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${day}.${m}.${d.getFullYear()}`;
}

/** Django `date:"Y-m-d"` — e.g. 2025-01-06; '—' for null/invalid. */
export function formatDateYmd(iso?: string | null): string {
  if (!iso) return '—';
  const d = parseDate(iso);
  if (!d) return '—';
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/** Django `date:"Y-m-d (D)"` — e.g. 2025-01-06 (Mon). */
export function formatDateWithWeekday(iso?: string | null): string {
  if (!iso) return '—';
  const d = parseDate(iso);
  if (!d) return '—';
  return `${formatDateYmd(iso)} (${WEEKDAYS[d.getDay()]})`;
}

/** Django `floatformat:N` — rounds to N decimals; '—' for null. */
export function formatFloat(
  value?: number | null,
  digits = 0,
): string {
  if (value == null || Number.isNaN(value)) return '—';
  return value.toFixed(digits);
}
