/** Display helpers for the dashboard SPA — ports of the retired
 *  template's date/duration renders (TIME_ZONE is UTC, so datetime
 *  fields format in UTC, not the browser's locale zone). */

const pad = (n: number): string => String(n).padStart(2, '0');

// Django's `N` month names are AP-style: March/April/June/July are
// spelled out and September is 'Sept.'.
const AP_MONTHS = [
  'Jan.',
  'Feb.',
  'March',
  'April',
  'May',
  'June',
  'July',
  'Aug.',
  'Sept.',
  'Oct.',
  'Nov.',
  'Dec.',
];

/** Django `date:"Y-m-d H:i"` on a UTC-aware ISO datetime —
 *  e.g. '2026-01-05 14:37'; '—' for null/invalid. */
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

/** Django `{{ row.day }}` renders DATE_FORMAT 'N j, Y' — e.g.
 *  'Jan. 5, 2026'; '—' for null/invalid. */
export function formatDay(iso?: string | null): string {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!m) return '—';
  const d = new Date(
    Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])),
  );
  return (
    `${AP_MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ` +
    `${d.getUTCFullYear()}`
  );
}

/** str(timedelta) duration from seconds: 'H:MM:SS' under a day,
 *  'N day(s), H:MM:SS' beyond — what the template's direct render
 *  printed; '—' for null. */
export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600) % 24;
  const days = Math.floor(total / 86400);
  const hms = `${h}:${pad(m)}:${pad(s)}`;
  return days ? `${days} day${days === 1 ? '' : 's'}, ${hms}` : hms;
}
