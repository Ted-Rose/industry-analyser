import { ReactNode } from 'react';
import { cx } from '../cx';

export interface FieldProps {
  /** Visible label text. Omit for unlabeled controls. */
  label?: ReactNode;
  /** id of the control — wires <label htmlFor>. */
  htmlFor?: string;
  /** Secondary line under the control. */
  hint?: ReactNode;
  /** Validation message — rendered with role="alert". */
  error?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Label + control + hint/error wrapper — plan §6 `ui/Field`.
 * Replaces `.filter-label` / `form-group` markup.
 */
export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
  className,
}: FieldProps) {
  return (
    <div className={cx('flex min-w-0 flex-col gap-1.5', className)}>
      {label !== undefined && label !== null && (
        <label
          htmlFor={htmlFor}
          className="text-sm font-medium text-fg"
        >
          {label}
        </label>
      )}
      {children}
      {hint && <p className="text-xs text-fg-subtle">{hint}</p>}
      {error && (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export default Field;
