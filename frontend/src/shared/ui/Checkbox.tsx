import { ComponentPropsWithRef, ReactNode } from 'react';
import { cx } from '../cx';

export interface CheckboxProps
  extends Omit<ComponentPropsWithRef<'input'>, 'type'> {
  /** Visible label — renders a wrapping <label>. */
  label?: ReactNode;
  /** Secondary line under the label. */
  description?: ReactNode;
  /** Dash state for parent nodes in checkbox trees. */
  indeterminate?: boolean;
}

/**
 * Styled checkbox with label — plan §6 `ui/Checkbox`.
 * `indeterminate` is a DOM-only property, applied through the
 * ref callback; a forwarded ref is composed in.
 */
export function Checkbox({
  label,
  description,
  indeterminate = false,
  className,
  ref,
  ...rest
}: CheckboxProps) {
  const setRefs = (el: HTMLInputElement | null) => {
    if (el) el.indeterminate = indeterminate;
    if (typeof ref === 'function') {
      ref(el);
    } else if (ref) {
      ref.current = el;
    }
  };

  const input = (
    <input
      type="checkbox"
      ref={setRefs}
      className={cx(
        'mt-0.5 size-4 shrink-0 accent-accent ' +
          'disabled:cursor-not-allowed disabled:opacity-50',
        !label && !description && 'mt-0',
        className,
      )}
      {...rest}
    />
  );

  if (label === undefined && description === undefined) {
    return input;
  }
  return (
    <label className="flex cursor-pointer items-start gap-2">
      {input}
      <span className="min-w-0">
        <span className="block text-sm text-fg">{label}</span>
        {description && (
          <span className="block text-xs text-fg-subtle">
            {description}
          </span>
        )}
      </span>
    </label>
  );
}

export default Checkbox;
