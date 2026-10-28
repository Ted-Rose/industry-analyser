import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import queryClient from '../shared/queryClient';
import ErrorBoundary from '../shared/components/ErrorBoundary';
import { initSentry } from '../shared/sentry';
import { initGlobalErrorHandlers } from '../shared/errorReporter';
import './tv.css';

// DSN-gated — no-ops until the spa-bootstrap payload carries one.
initSentry();
initGlobalErrorHandlers();

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* Django serves the shell for every path under /tv/ (the
            <path:subpath> catch-all), so the router mounts with
            basename '/tv' and routes are relative to it. */}
        <BrowserRouter basename="/tv">
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
