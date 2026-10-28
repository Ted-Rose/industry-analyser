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
import './vacancies.css';

// DSN-gated — no-ops until the spa-bootstrap payload carries one.
initSentry();
initGlobalErrorHandlers();

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* The vacancies SPA owns two public URL bases — /vacancies/*
            and /companies/* (company pages are routes of the same
            app) — so the router mounts without a basename and every
            route declares its absolute path. */}
        <BrowserRouter>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
