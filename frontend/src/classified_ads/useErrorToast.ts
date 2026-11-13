import { useEffect, useRef } from 'react';
import { errorDetail } from '../shared/api/errors';
import { pushToast } from '../shared/toasts';

/**
 * pushToast once per failed query — the VacancyList pattern.
 * Query failures surface both inline (ErrorState on first load)
 * and as a toast, so a failed refetch is visible while stale
 * rows stay on screen. The ref dedupes StrictMode's
 * double-effect and repeat failures of the same error object.
 */
export function useErrorToast(
  isError: boolean,
  error: unknown,
  message: string,
): void {
  const reported = useRef<unknown>(null);
  useEffect(() => {
    if (!isError) {
      reported.current = null;
      return;
    }
    if (reported.current === error) return;
    reported.current = error;
    pushToast(`${message} — ${errorDetail(error)}`, 'danger');
  }, [isError, error, message]);
}

export default useErrorToast;
