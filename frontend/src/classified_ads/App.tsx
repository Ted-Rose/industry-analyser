import { Navigate, Route, Routes } from 'react-router-dom';
import NavButtons from './components/NavButtons';
import Toasts from '../shared/components/Toasts';
import Index from './routes/Index';
import AdsTable from './routes/AdsTable';
import RegionConfig from './routes/RegionConfig';
import RegionStats from './routes/RegionStats';
import RegionStatsChildren from './routes/RegionStatsChildren';
import RegionAdsList from './routes/RegionAdsList';
import DailySightings from './routes/DailySightings';
import PropertyList from './routes/PropertyList';
import PropertyDetail from './routes/PropertyDetail';

/**
 * Router host for the classified_ads SPA (basename '/classified-ads').
 * Client routes mirror the pre-cutover URL names one-to-one, so
 * existing bookmarks and {% url 'classified_ads:…' %} reversals keep
 * working. /apartments and /houses were redirects to the rent tables —
 * kept as client-side Navigate. Unknown paths land back on the index.
 */
export default function App() {
  return (
    <>
      <NavButtons />
      <Toasts />
      <Routes>
        <Route path="/" element={<Index />} />
        <Route
          path="/apartments"
          element={<Navigate to="/apartments/rent" replace />}
        />
        <Route
          path="/apartments/rent"
          element={<AdsTable kind="apartment" deal="rent" />}
        />
        <Route
          path="/apartments/sale"
          element={<AdsTable kind="apartment" deal="sale" />}
        />
        <Route
          path="/apartments/regions/config"
          element={<RegionConfig kind="apartment" />}
        />
        <Route
          path="/apartments/regions/stats"
          element={<RegionStats kind="apartment" />}
        />
        <Route
          path="/apartments/regions/stats/:regionId/children"
          element={<RegionStatsChildren kind="apartment" />}
        />
        <Route
          path="/apartments/regions/:regionId/ads"
          element={<RegionAdsList kind="apartment" />}
        />
        <Route
          path="/houses"
          element={<Navigate to="/houses/rent" replace />}
        />
        <Route
          path="/houses/rent"
          element={<AdsTable kind="house" deal="rent" />}
        />
        <Route
          path="/houses/sale"
          element={<AdsTable kind="house" deal="sale" />}
        />
        <Route
          path="/houses/regions/config"
          element={<RegionConfig kind="house" />}
        />
        <Route
          path="/houses/regions/stats"
          element={<RegionStats kind="house" />}
        />
        <Route
          path="/houses/regions/stats/:regionId/children"
          element={<RegionStatsChildren kind="house" />}
        />
        <Route
          path="/houses/regions/:regionId/ads"
          element={<RegionAdsList kind="house" />}
        />
        <Route path="/daily-sightings" element={<DailySightings />} />
        <Route
          path="/properties/apartments"
          element={<PropertyList kind="apartment" />}
        />
        <Route
          path="/properties/apartments/:pk"
          element={<PropertyDetail kind="apartment" />}
        />
        <Route
          path="/properties/houses"
          element={<PropertyList kind="house" />}
        />
        <Route
          path="/properties/houses/:pk"
          element={<PropertyDetail kind="house" />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
