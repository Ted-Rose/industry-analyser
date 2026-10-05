import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  addKeyword,
  createSavedFilter,
  deleteSavedFilter,
  updateSavedFilter,
  type KeywordIn,
  type SavedFilterIn,
  type SavedFilterOut,
} from './api';

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

/** Saved-filter CRUD — only the `['vacancies', 'saved-filters']`
 *  list is affected, so invalidate just that key (the vacancy list
 *  itself doesn't depend on presets). */
export function useCreateSavedFilter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SavedFilterIn) => createSavedFilter(input),
    onSuccess: (created) => {
      // List the new preset immediately so the bar's derived
      // selection resolves it before the refetch lands.
      queryClient.setQueryData<SavedFilterOut[]>(
        ['vacancies', 'saved-filters'],
        (old) => (old ? [...old, created] : old),
      );
      queryClient.invalidateQueries({
        queryKey: ['vacancies', 'saved-filters'],
      });
    },
  });
}

export function useUpdateSavedFilter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: SavedFilterIn }) =>
      updateSavedFilter(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['vacancies', 'saved-filters'],
      });
    },
  });
}

export function useDeleteSavedFilter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteSavedFilter(id),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['vacancies', 'saved-filters'],
      });
    },
  });
}
