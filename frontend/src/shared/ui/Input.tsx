import { ComponentPropsWithRef } from 'react';
import { cx } from '../cx';

export interface InputProps
  extends ComponentPropsWithRef<'input'> {}

/**
 * Styled native <input> — plan §6 `ui/Input`. All native props
 * pass through, including `list` for <datalist> binding (tv
 * channel picker). The `text-lg sm:text-sm` pair is the iOS
 * zoom guard (inputs under 16px trigger page zoom on focus).
 */
export function Input({ className, type, ...rest }: InputProps) {
  return (
    <input
      type={type ?? 'text'}
      className={cx(
        'w-full min-w-0 rounded-md border border-border-strong ' +
          'bg-surface px-3 py-2 text-lg sm:text-sm text-fg ' +
          'placeholder:text-fg-subtle ' +
          'disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...rest}
    />
  );
}

export default Input;
