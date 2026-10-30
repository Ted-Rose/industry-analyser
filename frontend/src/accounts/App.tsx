import { Navigate, Route, Routes } from 'react-router-dom';
import Account from './routes/Account';
import Login from './routes/Login';
import Register from './routes/Register';

/**
 * Router host for the accounts SPA (basename '/accounts') — the
 * public login/register UI every auth bounce lands on. '/' is a
 * minimal account page (who am I + logout). Unknown paths land
 * back on it.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Account />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
