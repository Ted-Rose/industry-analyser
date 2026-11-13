import { useState } from 'react';
import { ThumbsDown, ThumbsUp } from 'lucide-react';
import { useSetCompanyPreference } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import IconButton from '../../shared/ui/IconButton';
import { Alert } from '../../shared/ui/ErrorState';
import type { CompanyPreference } from '../api';

/**
 * Like/dislike toggle for a company — only rendered for logged-in
 * users (the endpoint is session-authed). Clicking the active
 * button clears back to neutral (sends `preference: null`);
 * both buttons are disabled while the mutation is in flight. A
 * failed PUT surfaces inline — a 401 never reaches the error
 * handler (the api client navigates to login instead).
 */
export default function CompanyPreferenceButtons({
  companyId,
  preference,
}: {
  companyId: string;
  preference: CompanyPreference;
}) {
  const mutation = useSetCompanyPreference();
  const [error, setError] = useState('');
  const set = (next: 'like' | 'dislike') => {
    setError('');
    mutation.mutate(
      {
        companyId,
        preference: preference === next ? null : next,
      },
      { onError: (err) => setError(errorDetail(err)) },
    );
  };
  return (
    <>
      <span
        className="inline-flex items-center gap-1"
        role="group"
        aria-label="Company preference"
      >
        <IconButton
          icon={<ThumbsUp />}
          label="Like"
          pressed={preference === 'like'}
          disabled={mutation.isPending}
          onClick={() => set('like')}
        />
        <IconButton
          icon={<ThumbsDown />}
          label="Dislike"
          pressed={preference === 'dislike'}
          disabled={mutation.isPending}
          onClick={() => set('dislike')}
        />
      </span>
      {error && (
        <Alert tone="danger" className="mt-2">
          {error}
        </Alert>
      )}
    </>
  );
}
