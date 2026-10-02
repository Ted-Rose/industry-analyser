import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  saveRegionConfig,
  type Kind,
  type RegionConfigIn,
} from './api';
import { pushToast } from '../shared/toasts';
import { errorDetail } from '../shared/api/errors';

/**
 * TanStack Query mutation hooks for POST /api/classified-ads/….
 * Cache strategy: every classified_ads query is keyed under the
 * `['classified_ads', …]` prefix, so a successful mutation invalidates
 * that root — the refetched payloads carry the authoritative state
 * (e.g. fresh enabled counts on the config page). The response
 * `message` is surfaced as a toast, matching how the retired form
 * POST redirect signalled success; failures toast the error detail.
 */
export function useSaveRegionConfig(kind: Kind) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: Omit<RegionConfigIn, 'kind'>) =>
      saveRegionConfig({ ...input, kind }),
    onSuccess: (data) => {
      pushToast(data.message, 'success');
      queryClient.invalidateQueries({
        queryKey: ['classified_ads'],
      });
    },
    onError: (error) => {
      pushToast(errorDetail(error), 'danger');
    },
  });
}
