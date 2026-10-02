import { Navigate, Route, Routes } from 'react-router-dom';
import ProgramList from './routes/ProgramList';
import SpokiPage from './routes/SpokiPage';

/**
 * Router host for the tv SPA (basename '/tv'). '/' is the program
 * feed — the retired tv_programs:program_list view; '/spoki-page'
 * replaces the old spoki_page view (it fetches the article live via
 * GET /api/tv/spoki-page/). Unknown paths — including the retired
 * react/<uuid>/<reaction>/ form action — land back on the feed.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ProgramList />} />
      <Route path="/spoki-page" element={<SpokiPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
