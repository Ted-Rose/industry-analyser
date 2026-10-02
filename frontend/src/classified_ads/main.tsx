import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import queryClient from '../shared/queryClient';
import './classified_ads.css';

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* Django serves the shell for every path under
            /classified-ads/ (the named routes plus the
            <path:subpath> catch-all), so the router mounts with
            basename '/classified-ads' and routes are relative to
            it. The vite entry slug is 'classified_ads' (hyphens are
            illegal in SPA_ENTRY_RE); only the URL base is
            hyphenated. */}
        <BrowserRouter basename="/classified-ads">
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
