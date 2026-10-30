import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  X,
} from 'lucide-react';
import { dismissToast, useToasts, type ToastKind } from '../toasts';
import '../styles/ia-components.css';

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  danger: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

/**
 * Fixed bottom-left stack of mutation feedback alerts — SPA-side
 * counterpart of django.contrib.messages. Mounted once per SPA:
 * AppShell renders it, classified_ads still mounts its own until
 * PR-9. The `pushToast` API is unchanged; only the markup was
 * restyled (plan §6). Uses `ia-` classes from
 * styles/ia-components.css — imported above so vite co-bundles
 * the rules into every entry that mounts this component — so it
 * looks right even while Bootstrap is still loaded on legacy
 * entries (plan §4.4); its class names don't collide with any
 * Bootstrap selector.
 */
export function Toasts() {
  const toasts = useToasts();
  if (toasts.length === 0) return null;
  return (
    <div className="ia-toasts">
      {toasts.map((toast) => {
        const Icon = ICONS[toast.kind];
        return (
          <div
            key={toast.id}
            className={`ia-toast ia-toast--${toast.kind}`}
            role="alert"
          >
            <span className="ia-toast__icon" aria-hidden="true">
              <Icon size={16} />
            </span>
            <span className="ia-toast__text">{toast.text}</span>
            <button
              type="button"
              className="ia-toast__dismiss"
              aria-label="Dismiss"
              onClick={() => dismissToast(toast.id)}
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export default Toasts;
