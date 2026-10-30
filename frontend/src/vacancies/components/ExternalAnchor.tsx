import type { ReactNode } from 'react';
import { ExternalLink } from 'lucide-react';

/**
 * The shared external-link treatment — text plus the
 * ExternalLink glyph, opened in a new tab (plan §9.7's one
 * pattern). `rel="noopener"` alone: target="_blank" already
 * implies noopener in modern browsers, and noreferrer would
 * also strip the Referer.
 */
export default function ExternalAnchor({
  href,
  className,
  children,
}: {
  href: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener"
      className={className}
    >
      {children}
      <ExternalLink
        className="ml-0.5 inline size-3"
        aria-hidden="true"
      />
    </a>
  );
}
