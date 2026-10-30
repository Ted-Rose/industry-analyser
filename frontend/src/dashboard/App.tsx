import { Navigate, Route, Routes } from 'react-router-dom';
import Dashboard from './routes/Dashboard';

/**
 * Router host for the dashboard SPA (basename '/dashboard'). '/' is
 * the jobs dashboard — the retired scrape_jobs.dashboard view.
 * Every other path under /dashboard/ lands back on the dashboard;
 * the public landing page owns the site root.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
