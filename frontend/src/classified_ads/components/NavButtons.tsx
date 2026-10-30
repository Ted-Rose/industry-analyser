import { Link } from 'react-router-dom';

/**
 * The fixed nav-buttons block from the retired
 * classified_ads/base.html — 'Apps' leaves the SPA for the public
 * landing page at '/' (the app directory), 'Ads' returns to the
 * SPA index.
 */
export default function NavButtons() {
  return (
    <div className="nav-buttons">
      <a href="/" className="nav-btn">
        Apps
      </a>
      <Link to="/" className="nav-btn">
        Ads
      </Link>
    </div>
  );
}
