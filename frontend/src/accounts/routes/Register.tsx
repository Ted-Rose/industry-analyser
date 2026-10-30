import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { register } from '../api';
import { navigate, safeNext } from '../next';
import { errorDetail } from '../../shared/api/errors';

/**
 * POST /api/accounts/register/ — public registration; success
 * auto-logs-in and ends in a full-page navigation to `?next=`
 * (sanitized) like the login flow. Validation failures surface
 * the API's {error, detail, code} detail — weak passwords,
 * taken usernames/emails, mismatched confirmation.
 */
export default function Register() {
  const { search } = useLocation();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await register({
        username,
        email,
        password,
        password_confirm: passwordConfirm,
      });
      navigate(safeNext(search));
    } catch (err) {
      setError(errorDetail(err));
      setBusy(false);
    }
  };

  return (
    <div className="container py-4 accounts-page">
      <Link to="/login" className="back-link">
        ← Back to Sign in
      </Link>
      <h1 className="text-center">Register</h1>
      {error && (
        <div className="alert alert-danger" role="alert">
          {error}
        </div>
      )}
      <form onSubmit={submit}>
        <div className="mb-3">
          <label htmlFor="register-username" className="form-label">
            Username:
          </label>
          <input
            type="text"
            id="register-username"
            name="username"
            className="form-control"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="mb-3">
          <label htmlFor="register-email" className="form-label">
            Email <span className="text-muted">(optional):</span>
          </label>
          <input
            type="email"
            id="register-email"
            name="email"
            className="form-control"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>
        <div className="mb-3">
          <label htmlFor="register-password" className="form-label">
            Password:
          </label>
          <input
            type="password"
            id="register-password"
            name="password"
            className="form-control"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="mb-3">
          <label
            htmlFor="register-password-confirm"
            className="form-label"
          >
            Confirm password:
          </label>
          <input
            type="password"
            id="register-password-confirm"
            name="password_confirm"
            className="form-control"
            autoComplete="new-password"
            required
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
          />
        </div>
        <div className="d-grid">
          <button
            type="submit"
            className="btn btn-primary"
            disabled={busy}
          >
            {busy ? 'Registering…' : 'Register'}
          </button>
        </div>
      </form>
      <p className="text-muted text-center mt-3">
        Already registered? <Link to="/login">Sign in</Link>
      </p>
    </div>
  );
}
