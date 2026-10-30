import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { login } from '../api';
import { navigate, safeNext } from '../next';
import { errorDetail } from '../../shared/api/errors';
import PageContainer from '../../shared/layout/PageContainer';
import { Alert } from '../../shared/ui/ErrorState';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import Input from '../../shared/ui/Input';

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
    <PageContainer width="narrow">
      <Link
        to="/"
        className="mb-4 inline-block text-sm
          text-accent-text hover:underline"
      >
        ← Back to Account
      </Link>
      <h1 className="mb-4 text-center text-2xl font-semibold">
        Sign in
      </h1>
      {error && (
        <Alert tone="danger" className="mb-4">
          {error}
        </Alert>
      )}
      <form onSubmit={submit} className="space-y-4">
        <Field label="Username:" htmlFor="login-username">
          <Input
            type="text"
            id="login-username"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <Field label="Password:" htmlFor="login-password">
          <Input
            type="password"
            id="login-password"
            name="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Button
          type="submit"
          loading={busy}
          className="w-full"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
      <p className="mt-3 text-center text-sm text-fg-muted">
        No account yet?{' '}
        <Link
          to={`/register${search}`}
          className="text-accent-text hover:underline"
        >
          Register
        </Link>
      </p>
    </PageContainer>
  );
}
