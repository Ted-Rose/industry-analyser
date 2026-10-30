import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from '../shared/layout/AppShell';
import ReceiptsDashboard from './routes/ReceiptsDashboard';

/**
 * Router host for the receipts SPA (basename '/receipts'). '/' is
 * the spending dashboard — the retired receipts:dashboard view.
 * Unknown paths land back on it.
 *
 * AppShell owns the global chrome — TopNav (no navItems: a
 * single-screen app gets no tab row) and the Toasts mount.
 */
export default function App() {
  return (
    <AppShell appTitle="Receipts">
      <Routes>
        <Route path="/" element={<ReceiptsDashboard />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
