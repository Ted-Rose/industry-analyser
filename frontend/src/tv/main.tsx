import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import queryClient from '../shared/queryClient';
import './tv.css';

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* Django serves the shell for every path under /tv/ (the
            <path:subpath> catch-all), so the router mounts with
            basename '/tv' and routes are relative to it. */}
        <BrowserRouter basename="/tv">
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
