import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { login } from '../api';
import { navigate, safeNext } from '../next';
import { errorDetail } from '../../shared/api/errors';

/**
 * POST /api/accounts/login/ — session login. Success ends in a
 * full-page navigation to `?next=` (sanitized to a same-origin
 * pathname) so the destination page's bootstrap reflects the new
 * session. Failure surfaces the API's uniform {error, detail}
 * message — credential failures are a uniform 401
 * invalid_credentials, so no user enumeration here.
 */
export default function Login() {
  const { search } = useLocation();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await login({ username, password });
      navigate(safeNext(search));
    } catch (err) {
      setError(errorDetail(err));
      setBusy(false);
    }
  };

  return (
    <div className="container py-4 accounts-page">
      <Link to="/" className="back-link">
        ← Back to Account
      </Link>
      <h1 className="text-center">Sign in</h1>
      {error && (
        <div className="alert alert-danger" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <div className="mb-3">
          <label htmlFor="login-username" className="form-label">
            Username:
          </label>
          <input
            type="text"
            id="login-username"
            name="username"
            className="form-control"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="mb-3">
          <label htmlFor="login-password" className="form-label">
            Password:
          </label>
          <input
            type="password"
            id="login-password"
            name="password"
            className="form-control"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="d-grid">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy}
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </form>
      <p className="text-muted text-center mt-3">
        No account yet?{' '}
        <Link to={`/register${search}`}>Register</Link>
      </p>
    </div>
  );
}
