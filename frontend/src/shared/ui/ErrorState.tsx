import { ReactNode } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
} from 'lucide-react';
import { cx } from '../cx';
import Button from './Button';

export interface ErrorStateProps {
  /** Error object or pre-rendered message. */
  error?: unknown;
  title?: ReactNode;
  /** Renders a retry Button (wired to refetch in callers). */
  onRetry?: () => void;
  retryLabel?: string;
  className?: string;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return 'An unexpected error occurred. Please try again.';
}

/**
 * Centered error state — plan §6 `ui/ErrorState`. Replaces
 * Bootstrap `alert-danger` blocks and muted error text;
 * role="alert" announces it.
 */
export function ErrorState({
  error,
  title = 'Something went wrong',
  onRetry,
  retryLabel = 'Retry',
  className,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cx(
        'flex flex-col items-center gap-2 px-4 py-10 text-center',
        className,
      )}
    >
      <AlertCircle
        className="size-8 text-danger"
        aria-hidden="true"
      />
      <p className="text-sm font-medium text-fg">{title}</p>
      <p className="max-w-md text-sm text-fg-muted">
        {errorMessage(error)}
      </p>
      {onRetry && (
        <Button
          variant="secondary"
          size="sm"
          onClick={onRetry}
          className="mt-1"
        >
          {retryLabel}
        </Button>
      )}
    </div>
  );
}

export type AlertTone = 'info' | 'success' | 'warning' | 'danger';

const ALERT_TONES: Record<
  AlertTone,
  { box: string; icon: typeof Info }
> = {
  info: {
    box: 'border-info bg-info-subtle text-info',
    icon: Info,
  },
  success: {
    box: 'border-success bg-success-subtle text-success',
    icon: CheckCircle2,
  },
  warning: {
    box: 'border-warning bg-warning-subtle text-warning',
    icon: AlertTriangle,
  },
  danger: {
    box: 'border-danger bg-danger-subtle text-danger',
    icon: AlertCircle,
  },
};

export interface AlertProps {
  tone?: AlertTone;
  title?: ReactNode;
  children: ReactNode;
  /** Override the icon; pass null for none. */
  icon?: ReactNode | null;
  className?: string;
}

/**
 * Inline notice — plan §6 `ui/Alert`. Replaces `alert-danger`,
 * `NoDealTypeNote`, `CaveatNote`. role="alert" so it announces
 * without focus.
 */
export function Alert({
  tone = 'info',
  title,
  children,
  icon,
  className,
}: AlertProps) {
  const { box, icon: DefaultIcon } = ALERT_TONES[tone];
  return (
    <div
      role="alert"
      className={cx(
        'flex gap-2.5 rounded-md border p-3 text-sm',
        box,
        className,
      )}
    >
      {icon !== null && (
        <span className="mt-0.5 shrink-0" aria-hidden="true">
          {icon ?? <DefaultIcon className="size-4" />}
        </span>
      )}
      <div className="min-w-0">
        {title && <p className="font-medium">{title}</p>}
        <div className="[&_a]:underline">{children}</div>
      </div>
    </div>
  );
}

export default ErrorState;
