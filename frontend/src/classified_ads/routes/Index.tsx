import { Link } from 'react-router-dom';

/**
 * React port of index.html — a static link hub; it had no dynamic
 * context, so there is no API call behind this page.
 */
export default function Index() {
  return (
    <div className="index-page">
      <div className="container">
        <h1>Classified Ads</h1>
        <p className="subtitle">
          Real estate listings from SS.com Latvia
        </p>

        <section className="property-section">
          <h2 className="section-title">🏢 Apartments</h2>
          <ul className="nav-list">
            <li>
              <Link to="/apartments/rent">Browse Rental Apartments</Link>
            </li>
            <li>
              <Link to="/apartments/sale">
                Browse Apartments for Sale
              </Link>
            </li>
            <li>
              <Link to="/apartments/regions/stats">
                Apartment Regional Statistics
              </Link>
            </li>
            <li>
              <Link to="/properties/apartments">
                Apartment Properties (deduplicated)
              </Link>
            </li>
            <li>
              <Link to="/apartments/regions/config">
                Apartment Region Configuration
              </Link>
            </li>
          </ul>
        </section>

        <section className="property-section">
          <h2 className="section-title">🏡 Houses</h2>
          <ul className="nav-list">
            <li>
              <Link to="/houses/rent">Browse Rental Houses</Link>
            </li>
            <li>
              <Link to="/houses/sale">Browse Houses for Sale</Link>
            </li>
            <li>
              <Link to="/houses/regions/stats">
                House Regional Statistics
              </Link>
            </li>
            <li>
              <Link to="/properties/houses">
                House Properties (deduplicated)
              </Link>
            </li>
            <li>
              <Link to="/houses/regions/config">
                House Region Configuration
              </Link>
            </li>
          </ul>
        </section>

        <section className="property-section">
          <h2 className="section-title">📊 Reports</h2>
          <ul className="nav-list">
            <li>
              <Link to="/daily-sightings">Daily Sightings Report</Link>
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
