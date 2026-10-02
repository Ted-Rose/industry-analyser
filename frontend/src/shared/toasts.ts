/**
 * Minimal toast store for mutation feedback — floating Bootstrap
 * alerts rendered by `components/Toasts.tsx`. Lives at module level
 * so any mutation hook can report without prop drilling. Ported from
 * django-apps' frontend/src/shared/toasts.ts (minus i18n).
 */
import { useSyncExternalStore } from 'react';

export type ToastKind = 'success' | 'danger' | 'warning' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}

const AUTO_DISMISS_MS = 6000;

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

export function dismissToast(id: number) {
  toasts = toasts.filter((toast) => toast.id !== id);
  emit();
}

export function pushToast(text: string, kind: ToastKind = 'danger') {
  const id = nextId++;
  toasts = [...toasts, { id, kind, text }];
  emit();
  setTimeout(() => dismissToast(id), AUTO_DISMISS_MS);
  return id;
}

/** Test helper — empty the stack between tests. */
export function clearToasts() {
  toasts = [];
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(subscribe, () => toasts);
}
