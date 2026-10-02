import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import queryClient from '../shared/queryClient';

// Stage 0 stub — exercises the vite entry/manifest plumbing; the real
// vacancies SPA replaces this in its own migration stage.
const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <div className="p-3">Vacancies — React entry placeholder</div>
      </QueryClientProvider>
    </StrictMode>,
  );
}
