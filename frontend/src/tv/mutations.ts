import { useMutation, useQueryClient } from '@tanstack/react-query';
import { reactToProgram } from './api';

/**
 * TanStack Query mutation hooks for POST /api/tv/….
 * Cache strategy: every tv query is keyed under the `['tv', …]`
 * prefix, so a successful mutation invalidates that root — the
 * refetched payload carries the authoritative reaction state (a
 * dislike also hides the show unless ?show_disliked=1).
 */
export function useReactToProgram() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      programId,
      reaction,
    }: {
      programId: string;
      reaction: 'like' | 'dislike';
    }) => reactToProgram(programId, reaction),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tv'] });
    },
  });
}
