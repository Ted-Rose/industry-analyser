/** Display helpers ported from the fetcher templates.
 *  TIME_ZONE is 'UTC' — datetimes format in UTC like the
 *  templates' |date did, not the browser's local zone. */

/** Django `date:"Y.m.d"` — e.g. 2025.07.01; '—' for null/invalid. */
export function formatDate(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const m = String(d.getUTCMonth() + 1).padStart(2, '0');
  const day = String(d.getUTCDate()).padStart(2, '0');
  return `${d.getUTCFullYear()}.${m}.${day}`;
}

/** The salary cell: "€1 000 – €2 000" | "From €…" | "Up to €…" |
 *  '—' (template's floatformat:0 → round to whole euros). */
export function formatSalary(
  from?: number | null,
  to?: number | null,
): string {
  if (from != null && to != null) {
    return `€${Math.round(from)} – €${Math.round(to)}`;
  }
  if (from != null) return `From €${Math.round(from)}`;
  if (to != null) return `Up to €${Math.round(to)}`;
  return '—';
}

/** Deadline cells color red once past, green while active —
 *  mirrors `{% if vacancy.application_deadline < now %}`. */
export function deadlineClass(
  deadline?: string | null,
  now: Date = new Date(),
): 'deadline-past' | 'deadline-active' | '' {
  if (!deadline) return '';
  const d = new Date(deadline);
  if (Number.isNaN(d.getTime())) return '';
  return d.getTime() < now.getTime()
    ? 'deadline-past'
    : 'deadline-active';
}
