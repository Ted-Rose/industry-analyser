import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from '../shared/layout/AppShell';
import VacancyList from './routes/VacancyList';
import Keywords from './routes/Keywords';
import Companies from './routes/Companies';
import CompanyDetail from './routes/CompanyDetail';

/**
 * Router host for the vacancies SPA. Django serves the shell at
 * /vacancies/<path> and /companies/<path> (plus the named
 * /companies/<uuid:pk>/ route so {% url 'company_detail' %} keeps
 * reversing), so the React routes mirror those absolute paths —
 * /companies/<pk> is a client route, not a second mount.
 *
 * AppShell owns the global chrome — TopNav with the three NavTabs
 * sections below and the Toasts mount.
 */
export default function App() {
  return (
    <AppShell
      appTitle="Vacancies"
      navItems={[
        { to: '/vacancies', label: 'Vacancies', end: true },
        { to: '/companies', label: 'Companies' },
        { to: '/vacancies/keywords', label: 'Keywords' },
      ]}
    >
      <Routes>
        <Route path="/vacancies" element={<VacancyList />} />
        <Route path="/vacancies/keywords" element={<Keywords />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/companies/:pk" element={<CompanyDetail />} />
        <Route path="*" element={<Navigate to="/vacancies" replace />} />
      </Routes>
    </AppShell>
  );
}
