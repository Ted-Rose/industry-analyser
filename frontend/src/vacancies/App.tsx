import { Navigate, Route, Routes } from 'react-router-dom';
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
 */
export default function App() {
  return (
    <Routes>
      <Route path="/vacancies" element={<VacancyList />} />
      <Route path="/vacancies/keywords" element={<Keywords />} />
      <Route path="/companies" element={<Companies />} />
      <Route path="/companies/:pk" element={<CompanyDetail />} />
      <Route path="*" element={<Navigate to="/vacancies" replace />} />
    </Routes>
  );
}
