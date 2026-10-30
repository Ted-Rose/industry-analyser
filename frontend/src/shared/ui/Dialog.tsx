import {
  FormEvent,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { cx } from '../cx';
import Button from './Button';
import Field from './Field';
import Input from './Input';

export interface DialogProps {
  open: boolean;
  /** Esc / backdrop-click / programmatic close. */
  onClose: () => void;
  title: ReactNode;
  children?: ReactNode;
  /** Right-aligned action row (Buttons). */
  footer?: ReactNode;
  /** aria-label when the title isn't a plain string. */
  ariaLabel?: string;
  className?: string;
}

/**
 * Native <dialog> + showModal() — plan §6 `ui/Dialog`. Replaces
 * window.confirm/prompt and any hand-rolled overlays. Esc and
 * backdrop clicks funnel into onClose; focus trapping comes
 * free from the top layer.
 */
export function Dialog({
  open,
  onClose,
  title,
  children,
  footer,
  ariaLabel,
  className,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    // jsdom (vitest) ships no <dialog> methods — guard so the
    // component still renders its content under tests.
    if (
      open &&
      !el.open &&
      typeof el.showModal === 'function'
    ) {
      el.showModal();
    } else if (
      !open &&
      el.open &&
      typeof el.close === 'function'
    ) {
      el.close();
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-label={
        ariaLabel ??
        (typeof title === 'string' ? title : undefined)
      }
      onCancel={(event) => {
        // Always funnel Esc through onClose — never let the
        // browser close the dialog behind the parent's back.
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        // Clicks on the ::backdrop target the <dialog> itself.
        if (event.target === ref.current) onClose();
      }}
      className={cx(
        'm-auto w-full max-w-md rounded-xl border border-border ' +
          'bg-surface p-0 text-fg shadow-lg backdrop:bg-black/50',
        className,
      )}
    >
      <div className="border-b border-border px-5 py-4">
        <h2 className="text-lg font-semibold text-fg">{title}</h2>
      </div>
      {children && (
        <div className="px-5 py-4 text-sm text-fg-muted">
          {children}
        </div>
      )}
      {footer && (
        <div className="flex justify-end gap-2 border-t
          border-border px-5 py-3">
          {footer}
        </div>
      )}
    </dialog>
  );
}

export interface ConfirmOptions {
  title: ReactNode;
  body?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Confirm button gets the danger treatment. */
  danger?: boolean;
}

interface ConfirmState extends ConfirmOptions {
  resolve: (value: boolean) => void;
}

/**
 * Promise wrapper over Dialog for confirm flows — replaces
 * `window.confirm` (SavedFiltersBar). Render `confirmElement`
 * once near the root; `confirm()` resolves true/false, never
 * rejects.
 */
export function useConfirm() {
  const [state, setState] = useState<ConfirmState | null>(null);
  // Mirrors the resolve stored in `state` so unmount/replace can
  // settle a promise the dialog will never answer.
  const pendingRef = useRef<((value: boolean) => void) | null>(
    null,
  );

  const confirm = useCallback(
    (options: ConfirmOptions) =>
      new Promise<boolean>((resolve) => {
        // A second confirm() while one is open replaces it —
        // resolve the orphaned promise so the caller doesn't
        // hang forever.
        pendingRef.current?.(false);
        pendingRef.current = resolve;
        setState({ ...options, resolve });
      }),
    [],
  );

  const close = useCallback(
    (value: boolean) => {
      pendingRef.current = null;
      setState((current) => {
        current?.resolve(value);
        return null;
      });
    },
    [],
  );

  // Host unmounted with a confirm still open — settle the
  // stored promise (cancel) rather than leaking it.
  useEffect(
    () => () => {
      pendingRef.current?.(false);
      pendingRef.current = null;
    },
    [],
  );

  const confirmElement = (
    <Dialog
      open={state !== null}
      onClose={() => close(false)}
      title={state?.title ?? ''}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(false)}>
            {state?.cancelLabel ?? 'Cancel'}
          </Button>
          <Button
            variant={state?.danger ? 'danger' : 'primary'}
            onClick={() => close(true)}
          >
            {state?.confirmLabel ?? 'Confirm'}
          </Button>
        </>
      }
    >
      {state?.body}
    </Dialog>
  );

  return { confirm, confirmElement };
}

export interface PromptOptions {
  title: ReactNode;
  /** Field label above the input. */
  label?: string;
  defaultValue?: string;
  placeholder?: string;
  confirmLabel?: string;
  cancelLabel?: string;
}

interface PromptState extends PromptOptions {
  resolve: (value: string | null) => void;
}

/**
 * Promise wrapper over Dialog for text-input flows — replaces
 * `window.prompt` (SavedFiltersBar save/rename). Resolves the
 * entered string, or null on cancel.
 */
export function usePrompt() {
  const [state, setState] = useState<PromptState | null>(null);
  const [value, setValue] = useState('');
  // Mirrors the resolve stored in `state` so unmount/replace can
  // settle a promise the dialog will never answer.
  const pendingRef = useRef<
    ((value: string | null) => void) | null
  >(null);

  const prompt = useCallback(
    (options: PromptOptions) =>
      new Promise<string | null>((resolve) => {
        // See useConfirm: a second prompt() resolves the open
        // one as cancelled instead of orphaning it.
        pendingRef.current?.(null);
        pendingRef.current = resolve;
        setValue(options.defaultValue ?? '');
        setState({ ...options, resolve });
      }),
    [],
  );

  const close = useCallback((result: string | null) => {
    pendingRef.current = null;
    setState((current) => {
      current?.resolve(result);
      return null;
    });
  }, []);

  // Host unmounted with a prompt still open — settle the stored
  // promise (cancel) rather than leaking it.
  useEffect(
    () => () => {
      pendingRef.current?.(null);
      pendingRef.current = null;
    },
    [],
  );

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // Synthetic submit events bubble — stop the outer form (e.g.
    // a FilterBar the dialog is mounted inside) from also
    // applying on prompt save.
    event.stopPropagation();
    close(value);
  };

  const promptElement = (
    <Dialog
      open={state !== null}
      onClose={() => close(null)}
      title={state?.title ?? ''}
      footer={
        <>
          <Button variant="ghost" onClick={() => close(null)}>
            {state?.cancelLabel ?? 'Cancel'}
          </Button>
          <Button type="submit" form="ia-prompt-form">
            {state?.confirmLabel ?? 'Save'}
          </Button>
        </>
      }
    >
      <form id="ia-prompt-form" onSubmit={submit}>
        <Field label={state?.label} htmlFor="ia-prompt-input">
          <Input
            id="ia-prompt-input"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={state?.placeholder}
            autoFocus
          />
        </Field>
      </form>
    </Dialog>
  );

  return { prompt, promptElement };
}

export default Dialog;
