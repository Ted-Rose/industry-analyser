/**
 * Tiny className merge helper — every shared component accepts a
 * `className` that is appended to its defaults through `cx()`
 * (plan §6). Falsy parts are dropped so conditional classes stay
 * readable.
 */
export function cx(
  ...parts: Array<string | false | null | undefined>
): string {
  return parts.filter(Boolean).join(' ');
}

export default cx;
