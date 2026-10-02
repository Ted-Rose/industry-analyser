/** Display helpers for the dashboard SPA — ports of the retired
 *  template's date/duration renders (TIME_ZONE is UTC, so datetime
 *  fields format in UTC, not the browser's locale zone). */

const pad = (n: number): string => String(n).padStart(2, '0');

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

/** str(timedelta)-ish duration from seconds: 'H:MM:SS' under a day,
 *  'Nd H:MM:SS' beyond (the template rendered the timedelta
 *  directly / via timeuntil); '—' for null. */
export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  const total = Math.max(0, Math.round(seconds));
  const s = total % 60;
  const m = Math.floor(total / 60) % 60;
  const h = Math.floor(total / 3600) % 24;
  const days = Math.floor(total / 86400);
  const hms = `${h}:${pad(m)}:${pad(s)}`;
  return days ? `${days}d ${hms}` : hms;
}
