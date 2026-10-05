import { useState } from 'react';
import { useSetCompanyPreference } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
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
        className="btn-group btn-group-sm"
        role="group"
        aria-label="Company preference"
      >
        <button
          type="button"
          className={`btn btn-sm ${
            preference === 'like'
              ? 'btn-success'
              : 'btn-outline-success'
          }`}
          disabled={mutation.isPending}
          aria-pressed={preference === 'like'}
          onClick={() => set('like')}
        >
          Like
        </button>
        <button
          type="button"
          className={`btn btn-sm ${
            preference === 'dislike'
              ? 'btn-danger'
              : 'btn-outline-danger'
          }`}
          disabled={mutation.isPending}
          aria-pressed={preference === 'dislike'}
          onClick={() => set('dislike')}
        >
          Dislike
        </button>
      </span>
      {error && (
        <div
          className="alert alert-danger py-2 mt-2 mb-0"
          role="alert"
        >
          {error}
        </div>
      )}
    </>
  );
}
