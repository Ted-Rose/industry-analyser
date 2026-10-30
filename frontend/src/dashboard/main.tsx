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
import '../shared/styles/app.css';

// DSN-gated — no-ops until the spa-bootstrap payload carries one.
initSentry();
initGlobalErrorHandlers();

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* The dashboard SPA mounts at /dashboard/ (the public
            landing page owns the site root): Django serves the
            shell on 'dashboard/' plus 'dashboard/<path:subpath>'.
            The shell itself is login-required (react_app, not the
            public variant) — an anonymous visitor bounces to
            /admin/login/ before this bundle ever runs. basename
            '/dashboard' — routes are relative to the mount. */}
        <BrowserRouter basename="/dashboard">
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
