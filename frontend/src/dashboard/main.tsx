import 'vite/modulepreload-polyfill';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import queryClient from '../shared/queryClient';
import './dashboard.css';

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        {/* The dashboard SPA owns the site root: Django serves the
            shell on '' plus the '<path:subpath>' catch-all that is
            appended last in urlpatterns. The shell itself is
            login-required (react_app, not the public variant) — an
            anonymous visitor bounces to /admin/login/ before this
            bundle ever runs. basename '/' — routes are absolute
            site paths. */}
        <BrowserRouter basename="/">
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}
