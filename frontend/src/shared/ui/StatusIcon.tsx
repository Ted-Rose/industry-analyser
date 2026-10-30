import { Check, X } from 'lucide-react';
import { cx } from '../cx';

export interface StatusIconProps {
  /** Boolean cell value — check when true, x when false. */
  value: boolean;
  /** Accessible names (screen-reader text). */
  trueLabel?: string;
  falseLabel?: string;
  className?: string;
}

/**
 * Check/x glyph for boolean cells — plan §6 `ui/StatusIcon`
 * (dashboard "Enabled" column). The accessible name carries the
 * meaning, the icon is decorative.
 */
export function StatusIcon({
  value,
  trueLabel = 'Yes',
  falseLabel = 'No',
  className,
}: StatusIconProps) {
  const Icon = value ? Check : X;
  return (
    <span
      role="img"
      aria-label={value ? trueLabel : falseLabel}
      className={cx(
        'inline-flex',
        value ? 'text-success' : 'text-fg-subtle',
        className,
      )}
    >
      <Icon className="size-4" aria-hidden="true" />
    </span>
  );
}

export default StatusIcon;
