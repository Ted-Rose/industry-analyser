import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import queryClient from '../shared/queryClient';

// Stage 0 stub — exercises the vite entry/manifest plumbing; the real
// dashboard SPA (mounted at /, login-required) replaces this in the
// last migration stage.
const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <div className="p-3">Dashboard — React entry placeholder</div>
      </QueryClientProvider>
    </StrictMode>,
  );
}
