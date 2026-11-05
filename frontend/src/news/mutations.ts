import { useMutation, useQueryClient } from '@tanstack/react-query';
import { savePreferences, type PreferenceRowIn } from './api';

/**
 * TanStack Query mutation hooks for POST /api/news/….
 * Cache strategy: every news query is keyed under the
 * `['news', …]` prefix, so a successful save invalidates
 * that root — the refetched preferences payload carries the
 * authoritative checked/rank state.
 */
export function useSavePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rows: PreferenceRowIn[]) => savePreferences(rows),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news'] });
    },
  });
}
