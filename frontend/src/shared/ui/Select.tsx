import { ComponentPropsWithRef } from 'react';
import { ChevronDown } from 'lucide-react';
import { cx } from '../cx';

export interface SelectProps
  extends ComponentPropsWithRef<'select'> {}

/**
 * Styled native <select> — plan §6 `ui/Select`. Children pass
 * through so callers can render <option> and <optgroup> directly
 * (region groups in classified_ads). A chevron replaces the
 * native arrow via appearance-none.
 */
export function Select({
  className,
  children,
  ...rest
}: SelectProps) {
  return (
    <div className="relative">
      <select
        className={cx(
          'w-full appearance-none rounded-md border ' +
            'border-border-strong bg-surface py-2 pl-3 pr-9 ' +
            'text-lg sm:text-sm text-fg ' +
            'disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-2.5
          top-1/2 size-4 -translate-y-1/2 text-fg-subtle"
        aria-hidden="true"
      />
    </div>
  );
}

export default Select;
