import { useMutation, useQueryClient } from '@tanstack/react-query';
import { addKeyword, type KeywordIn } from './api';

/**
 * TanStack Query mutation hooks for POST /api/vacancies/….
 * Cache strategy: every vacancies query is keyed under the
 * `['vacancies', …]` prefix, so a successful mutation invalidates
 * that root — the refetched payloads carry the authoritative state
 * (e.g. the new keyword in the filter option list).
 */
export function useAddKeyword() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: KeywordIn) => addKeyword(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vacancies'] });
    },
  });
}
