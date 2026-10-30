import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { register } from '../api';
import { navigate, safeNext } from '../next';
import { errorDetail } from '../../shared/api/errors';
import PageContainer from '../../shared/layout/PageContainer';
import { Alert } from '../../shared/ui/ErrorState';
import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import Input from '../../shared/ui/Input';

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
    <PageContainer width="narrow">
      <Link
        to={`/login${search}`}
        className="mb-4 inline-block text-sm
          text-accent-text hover:underline"
      >
        ← Back to Sign in
      </Link>
      <h1 className="mb-4 text-center text-2xl font-semibold">
        Register
      </h1>
      {error && (
        <Alert tone="danger" className="mb-4">
          {error}
        </Alert>
      )}
      <form onSubmit={submit} className="space-y-4">
        <Field label="Username:" htmlFor="register-username">
          <Input
            type="text"
            id="register-username"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <Field
          label={
            <>
              Email{' '}
              <span className="text-fg-muted">(optional):</span>
            </>
          }
          htmlFor="register-email"
        >
          <Input
            type="email"
            id="register-email"
            name="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </Field>
        <Field label="Password:" htmlFor="register-password">
          <Input
            type="password"
            id="register-password"
            name="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <Field
          label="Confirm password:"
          htmlFor="register-password-confirm"
        >
          <Input
            type="password"
            id="register-password-confirm"
            name="password_confirm"
            autoComplete="new-password"
            required
            value={passwordConfirm}
            onChange={(e) => setPasswordConfirm(e.target.value)}
          />
        </Field>
        <Button
          type="submit"
          loading={busy}
          className="w-full"
        >
          {busy ? 'Registering…' : 'Register'}
        </Button>
      </form>
      <p className="mt-3 text-center text-sm text-fg-muted">
        Already registered?{' '}
        <Link
          to={`/login${search}`}
          className="text-accent-text hover:underline"
        >
          Sign in
        </Link>
      </p>
    </PageContainer>
  );
}
