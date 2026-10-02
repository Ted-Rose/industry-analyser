import { QueryClient } from '@tanstack/react-query';

/**
 * One QueryClient per SPA bundle — created here (not in main.tsx)
 * so non-component code can invalidate queries without a hook
 * context. All entries share the same options: one retry keeps
 * transient network errors from flashing error states; real failures
 * still surface via ApiError.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default queryClient;
