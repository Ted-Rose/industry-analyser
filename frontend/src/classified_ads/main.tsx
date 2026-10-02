import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import queryClient from '../shared/queryClient';

// Stage 0 stub — exercises the vite entry/manifest plumbing; the real
// classified_ads SPA replaces this in its own migration stage. The
// public URL base is /classified-ads/ while the entry slug uses an
// underscore (SPA_ENTRY_RE is [a-z0-9_]+).
const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <div className="p-3">
          Classified Ads — React entry placeholder
        </div>
      </QueryClientProvider>
    </StrictMode>,
  );
}
