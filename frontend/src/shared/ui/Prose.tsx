import { ReactNode } from 'react';
import { cx } from '../cx';

export interface ProseProps {
  /** Raw HTML — rendered via dangerouslySetInnerHTML. */
  html?: string;
  children?: ReactNode;
  className?: string;
}

/**
 * Typographic wrapper for injected/flow content — plan §6
 * `ui/Prose`. The `.prose` component-layer styles (h1–h4, lists,
 * links, images) live in site.css; this is just the React mount
 * point — pass `html` for server-escaped markup (SpokiPage).
 */
export function Prose({ html, children, className }: ProseProps) {
  if (html !== undefined) {
    return (
      <div
        className={cx('prose', className)}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }
  return <div className={cx('prose', className)}>{children}</div>;
}

export default Prose;
