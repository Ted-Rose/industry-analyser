import { Navigate, Route, Routes } from 'react-router-dom';
import ReceiptsDashboard from './routes/ReceiptsDashboard';

/**
 * Router host for the receipts SPA (basename '/receipts'). '/' is
 * the spending dashboard — the retired receipts:dashboard view.
 * Unknown paths land back on it.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<ReceiptsDashboard />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
