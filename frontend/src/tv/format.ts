/** Display helpers ported from the retired program_list.html.
 *  TIME_ZONE is 'UTC', so datetimes format in UTC like the
 *  templates did (and match the API's UTC date bucketing), not the
 *  browser's local zone. */

// Django's `N` month names are AP-style: March/April/June/July are
// spelled out and September is 'Sept.'.
const MONTHS = [
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

/** Django `{{ program.start_time }}` renders DATETIME_FORMAT
 *  "N j, Y, P" → e.g. "Oct. 2, 2026, 3:15 p.m." — with `P`'s
 *  noon/midnight special cases; '—' on failure. */
export function formatStartTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const date = `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  const h = d.getUTCHours();
  const m = d.getUTCMinutes();
  if (h === 0 && m === 0) return `${date}, midnight`;
  if (h === 12 && m === 0) return `${date}, noon`;
  const h12 = h % 12 || 12;
  const minutes = String(m).padStart(2, '0');
  const meridiem = h < 12 ? 'a.m.' : 'p.m.';
  return `${date}, ${h12}:${minutes} ${meridiem}`;
}

/** The card's "Rating:" cell — `show.imdb_rating|default:
 *  program.imdb_rating` in the template. Django's |default falls
 *  back on any falsy value, so a 0.0 show rating shows the
 *  program's scraped string instead. */
export function displayRating(
  showImdbRating?: string | number | null,
  programImdbRating?: string | null,
): string | null {
  if (
    showImdbRating != null &&
    showImdbRating !== '' &&
    Number(showImdbRating) !== 0
  ) {
    return String(showImdbRating);
  }
  return programImdbRating ?? null;
}
