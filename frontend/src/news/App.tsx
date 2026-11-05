import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from '../shared/layout/AppShell';
import DigestDetail from './routes/DigestDetail';
import DigestList from './routes/DigestList';
import Preferences from './routes/Preferences';

/**
 * Router host for the news SPA (basename '/news'). '/' is
 * the digest index — the retired digest_list view;
 * '/preferences' the outlet ranking form (session-auth at
 * the API layer — anonymous readers bounce to
 * /accounts/login/ via the 401 handshake); '/:date' the
 * digest detail. Unknown paths — including the retired
 * /news/audio/ and /news/story/<pk>/fragment/ endpoints —
 * land back on the digest index.
 *
 * AppShell owns the global chrome — TopNav with the NavTabs
 * sections below and the Toasts mount.
 */
export default function App() {
  return (
    <AppShell
      appTitle="News"
      navItems={[
        { to: '/', label: 'Digest', end: true },
        { to: '/preferences', label: 'Portālu izvēle' },
      ]}
    >
      <Routes>
        <Route path="/" element={<DigestList />} />
        <Route path="/preferences" element={<Preferences />} />
        <Route path="/:date" element={<DigestDetail />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
