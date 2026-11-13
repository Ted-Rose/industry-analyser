import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { fetchMe, logout } from '../api';
import { navigate } from '../next';
import { errorDetail } from '../../shared/api/errors';
import PageContainer from '../../shared/layout/PageContainer';
import { Alert } from '../../shared/ui/ErrorState';
import Button from '../../shared/ui/Button';
import DescriptionList from '../../shared/ui/DescriptionList';

/**
 * The account index — shows the GET /api/accounts/me/ payload:
 * the signed-in user plus a logout button, or login/register
 * links for anonymous visitors. me/ never 401s, so this page is
 * the one place a client can safely probe auth state. Logout
 * ends in a full-page navigation to '/' so the landing page
 * renders against the ended session.
 */
export default function Account() {
  const me = useQuery({
    queryKey: ['accounts', 'me'],
    queryFn: fetchMe,
  });

  const signOut = async () => {
    await logout();
    navigate('/');
  };

  if (me.isPending) {
    return (
      <PageContainer width="narrow">
        <p className="text-sm text-fg-muted">Loading…</p>
      </PageContainer>
    );
  }

  if (me.isError) {
    return (
      <PageContainer width="narrow">
        <Alert tone="danger">{errorDetail(me.error)}</Alert>
      </PageContainer>
    );
  }

  const user = me.data.user;
  return (
    <PageContainer width="narrow">
      <h1 className="mb-4 text-center text-2xl font-semibold">
        Account
      </h1>
      {user ? (
        <div className="space-y-4">
          <DescriptionList
            items={[
              { term: 'Username', description: user.username },
              {
                term: 'Email',
                description: user.email || '—',
              },
            ]}
          />
          <Button
            type="button"
            variant="danger"
            className="w-full"
            onClick={signOut}
          >
            Sign out
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-center text-sm text-fg-muted">
            You are not signed in.
          </p>
          <div className="flex flex-col gap-2">
            <Button as={Link} to="/login">
              Sign in
            </Button>
            <Button as={Link} to="/register" variant="secondary">
              Register
            </Button>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
