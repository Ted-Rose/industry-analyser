import {
  ComponentPropsWithRef,
  ElementType,
  ReactNode,
} from 'react';
import { cx } from '../cx';

export type IconButtonVariant = 'ghost' | 'outline';
export type IconButtonSize = 'sm' | 'md';

const VARIANTS: Record<IconButtonVariant, string> = {
  ghost: 'text-fg-muted hover:bg-surface-2 hover:text-fg',
  outline:
    'text-fg-muted border border-border-strong bg-surface ' +
    'hover:bg-surface-2 hover:text-fg',
};

const SIZES: Record<IconButtonSize, string> = {
  sm: 'size-8 rounded-md [&_svg]:size-4',
  md: 'size-10 rounded-md [&_svg]:size-5',
};

export interface IconButtonProps
  extends ComponentPropsWithRef<'button'> {
  /** The lucide icon (or any node) rendered inside. */
  icon: ReactNode;
  /** Required accessible name — becomes aria-label. */
  label: string;
  variant?: IconButtonVariant;
  size?: IconButtonSize;
  /** Toggle state — sets aria-pressed (reaction buttons). */
  pressed?: boolean;
  as?: ElementType;
}

/**
 * Square icon-only button — plan §6 `ui/IconButton`. Replaces
 * `.reaction-btn`, `.airings-toggle` and ad-hoc dismiss buttons.
 * `pressed` maps to aria-pressed for like/dislike toggles.
 */
export function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  pressed,
  as,
  className,
  type,
  ...rest
}: IconButtonProps) {
  const Component = (as ?? 'button') as ElementType;
  return (
    <Component
      type={Component === 'button' ? (type ?? 'button') : undefined}
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      className={cx(
        'inline-flex shrink-0 items-center justify-center ' +
          'transition-colors motion-safe:duration-120 ease-ia ' +
          'disabled:cursor-not-allowed disabled:opacity-50 ' +
          'aria-pressed:bg-accent-subtle aria-pressed:text-accent-text',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {icon}
    </Component>
  );
}

export default IconButton;
