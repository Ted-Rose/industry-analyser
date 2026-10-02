/** Display helpers ported from the retired program_list.html. */

const MONTHS = [
  'Jan.',
  'Feb.',
  'Mar.',
  'Apr.',
  'May',
  'Jun.',
  'Jul.',
  'Aug.',
  'Sep.',
  'Oct.',
  'Nov.',
  'Dec.',
];

/** Django `{{ program.start_time }}` renders DATETIME_FORMAT
 *  "N j, Y, P" → e.g. "Oct. 2, 2026, 3:15 p.m." — '—' on failure. */
export function formatStartTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const h12 = d.getHours() % 12 || 12;
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const meridiem = d.getHours() < 12 ? 'a.m.' : 'p.m.';
  return (
    `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}, ` +
    `${h12}:${minutes} ${meridiem}`
  );
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
