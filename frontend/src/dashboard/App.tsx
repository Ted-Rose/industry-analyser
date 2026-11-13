import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from '../shared/layout/AppShell';
import Dashboard from './routes/Dashboard';

/**
 * Router host for the dashboard SPA (basename '/dashboard'). '/' is
 * the jobs dashboard — the retired scrape_jobs.dashboard view.
 * Every other path under /dashboard/ lands back on the dashboard;
 * the public landing page owns the site root.
 *
 * AppShell owns the global chrome — TopNav (no navItems: a
 * single-screen app gets no tab row) and the Toasts mount.
 */
export default function App() {
  return (
    <AppShell appTitle="Dashboard">
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
