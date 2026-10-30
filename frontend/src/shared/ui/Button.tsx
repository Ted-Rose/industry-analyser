import {
  ComponentPropsWithRef,
  ElementType,
  ReactNode,
} from 'react';
import { LoaderCircle } from 'lucide-react';
import { cx } from '../cx';

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger';
export type ButtonSize = 'sm' | 'md';

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-accent-fg border border-transparent ' +
    'hover:bg-accent-hover',
  secondary:
    'bg-surface text-fg border border-border-strong ' +
    'hover:bg-surface-2',
  ghost:
    'bg-transparent text-fg-muted border border-transparent ' +
    'hover:bg-surface-2 hover:text-fg',
  danger:
    'bg-danger text-white border border-transparent ' +
    'hover:brightness-110',
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-8 px-3 text-sm gap-1.5 rounded-md',
  md: 'h-10 px-4 text-sm gap-2 rounded-md',
};

export interface ButtonProps
  extends ComponentPropsWithRef<'button'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and disables the button. */
  loading?: boolean;
  leftIcon?: ReactNode;
  /** Render as another element — e.g. 'a' or a router Link. */
  as?: ElementType;
}

/**
 * The one button — plan §6 `ui/Button`. Replaces Bootstrap's
 * `btn-*`, `.nav-btn` and bare `<button>` styles. `as` lets the
 * same treatment ride on links (`as="a"`, `as={Link}`); extra
 * props (`href`, `to`, `target`, …) pass through.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  leftIcon,
  as,
  className,
  children,
  disabled,
  type,
  ...rest
}: ButtonProps) {
  const Component = (as ?? 'button') as ElementType;
  const isButton = Component === 'button';
  return (
    <Component
      type={isButton ? (type ?? 'button') : undefined}
      className={cx(
        'inline-flex select-none items-center justify-center ' +
          'font-medium whitespace-nowrap transition-colors ' +
          'motion-safe:duration-120 ease-ia ' +
          'disabled:cursor-not-allowed disabled:opacity-50 ' +
          'aria-disabled:cursor-not-allowed aria-disabled:opacity-50',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      disabled={isButton ? disabled || loading : undefined}
      aria-disabled={
        !isButton && (disabled || loading) ? true : undefined
      }
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? (
        <LoaderCircle
          className="size-4 motion-safe:animate-spin"
          aria-hidden="true"
        />
      ) : (
        leftIcon
      )}
      {children}
    </Component>
  );
}

export default Button;
