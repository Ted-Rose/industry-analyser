import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { fetchMe, logout } from '../api';
import { navigate } from '../next';
import { errorDetail } from '../../shared/api/errors';

/**
 * The account index — shows the GET /api/accounts/me/ payload:
 * the signed-in user plus a logout button, or login/register
 * links for anonymous visitors. me/ never 401s, so this page is
 * the one place a client can safely probe auth state. Logout
 * ends in a full-page navigation to '/' so the landing page
 * renders against the ended session.
 */
export default function Account() {
  const me = useQuery({ queryKey: ['accounts', 'me'], queryFn: fetchMe });

  const signOut = async () => {
    await logout();
    navigate('/');
  };

  if (me.isPending) {
    return (
      <div className="container py-4 accounts-page">
        <p className="text-muted">Loading…</p>
      </div>
    );
  }

  if (me.isError) {
    return (
      <div className="container py-4 accounts-page">
        <div className="alert alert-danger" role="alert">
          {errorDetail(me.error)}
        </div>
      </div>
    );
  }

  const user = me.data.user;
  return (
    <div className="container py-4 accounts-page">
      <h1 className="text-center">Account</h1>
      {user ? (
        <>
          <dl>
            <dt>Username</dt>
            <dd>{user.username}</dd>
            <dt>Email</dt>
            <dd>{user.email || '—'}</dd>
          </dl>
          <div className="d-grid">
            <button
              type="button"
              className="btn btn-outline-danger"
              onClick={signOut}
            >
              Sign out
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-muted text-center">
            You are not signed in.
          </p>
          <div className="d-grid gap-2">
            <Link to="/login" className="btn btn-primary">
              Sign in
            </Link>
            <Link to="/register" className="btn btn-outline-primary">
              Register
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
