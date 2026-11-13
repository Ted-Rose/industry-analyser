import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  savePreferences,
  subscribeDigestTask,
  unsubscribeDigestTask,
  type PreferenceRowIn,
} from './api';

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

/** POST subscribe — the returned status payload replaces the
 *  card's state via the ['news'] root invalidation. */
export function useSubscribeDigestTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => subscribeDigestTask(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news'] });
    },
  });
}

/** POST unsubscribe — same payload, is_enabled flips off. */
export function useUnsubscribeDigestTask() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unsubscribeDigestTask(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['news'] });
    },
  });
}
