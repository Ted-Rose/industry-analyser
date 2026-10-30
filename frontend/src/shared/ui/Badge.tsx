import { ReactNode } from 'react';
import { cx } from '../cx';

export type BadgeTone =
  | 'neutral'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info';

export type BadgeVariant = 'subtle' | 'outline';
export type BadgeSize = 'sm' | 'md';

const TONES: Record<BadgeTone, Record<BadgeVariant, string>> = {
  neutral: {
    subtle: 'bg-surface-2 text-fg-muted',
    outline: 'border-border-strong text-fg-muted',
  },
  accent: {
    subtle: 'bg-accent-subtle text-accent-text',
    outline: 'border-accent text-accent-text',
  },
  success: {
    subtle: 'bg-success-subtle text-success',
    outline: 'border-success text-success',
  },
  warning: {
    subtle: 'bg-warning-subtle text-warning',
    outline: 'border-warning text-warning',
  },
  danger: {
    subtle: 'bg-danger-subtle text-danger',
    outline: 'border-danger text-danger',
  },
  info: {
    subtle: 'bg-info-subtle text-info',
    outline: 'border-info text-info',
  },
};

const SIZES: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-xs rounded-sm',
  md: 'px-2 py-0.5 text-xs rounded-md',
};

export interface BadgeProps {
  tone?: BadgeTone;
  variant?: BadgeVariant;
  size?: BadgeSize;
  /** Renders an <a> (external links — portal, site ↗). */
  href?: string;
  className?: string;
  children: ReactNode;
}

/**
 * Inline status/tag pill — plan §6 `ui/Badge`. Replaces the
 * `.industry`/`.profession`/`.source-tag`/`.keyword-match-badge`/
 * `.pg-badge`/`badge bg-*` sprawl.
 */
export function Badge({
  tone = 'neutral',
  variant = 'subtle',
  size = 'sm',
  href,
  className,
  children,
}: BadgeProps) {
  const Component = href ? 'a' : 'span';
  return (
    <Component
      href={href}
      className={cx(
        'inline-flex items-center gap-1 font-medium ' +
          'whitespace-nowrap',
        variant === 'outline' && 'border',
        TONES[tone][variant],
        SIZES[size],
        href && 'hover:underline',
        className,
      )}
    >
      {children}
    </Component>
  );
}

const STATUS_TONES: Record<string, BadgeTone> = {
  SUCCESS: 'success',
  PARTIAL: 'warning',
  FAILED: 'danger',
  RUNNING: 'info',
};

export interface StatusBadgeProps {
  /** Run status string — SUCCESS/PARTIAL/FAILED/RUNNING. */
  status: string;
  className?: string;
}

/**
 * Badge for scrape-run statuses — plan §6 `StatusBadge`.
 * RUNNING pulses (motion-safe) as the liveness cue (§8.16).
 */
export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <Badge
      tone={STATUS_TONES[status] ?? 'neutral'}
      className={cx(
        status === 'RUNNING' && 'motion-safe:animate-pulse',
        className,
      )}
    >
      {status}
    </Badge>
  );
}

export default Badge;
