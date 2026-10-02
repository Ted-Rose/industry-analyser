import { Navigate, Route, Routes } from 'react-router-dom';
import Dashboard from './routes/Dashboard';

/**
 * Router host for the dashboard SPA (basename '/'). '/' is the jobs
 * dashboard — the retired scrape_jobs.dashboard view. Every other
 * root path that reaches React (the Django catch-all only fires for
 * paths not claimed earlier in urlpatterns — admin/, api/,
 * vacancies/, tv/, classified-ads/, accounts/ all resolve before
 * it) lands back on the dashboard.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
