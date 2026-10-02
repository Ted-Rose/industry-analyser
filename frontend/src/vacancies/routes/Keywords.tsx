import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAddKeyword } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';

/**
 * React replacement for the retired /add_keyword/ page (301'd here).
 * The old HARD_CODED_PASSWORD gate is gone — the POST is session-authed
 * now, so anonymous users see a hint and the API client bounces them
 * to /admin/login/ on the 401. `only_filter` stays pre-checked, as in
 * the template form.
 */
export default function Keywords() {
  const { user } = useBootstrap();
  const [name, setName] = useState('');
  const [onlyFilter, setOnlyFilter] = useState(true);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const addKeyword = useAddKeyword();

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    setError('');
    addKeyword.mutate(
      { name, only_filter: onlyFilter },
      {
        onSuccess: (data) => {
          setMessage(data.message);
          setName('');
        },
        onError: (err) => setError(errorDetail(err)),
      },
    );
  };

  return (
    <div className="container py-4 vacancies-page">
      <Link to="/vacancies" className="back-link">
        ← Back to Vacancies
      </Link>
      <h1 className="text-center">Add Keyword</h1>
      {!user && (
        <p className="text-muted text-center">
          Adding a keyword requires an admin login — submitting will
          send you to the sign-in page.
        </p>
      )}
      <form onSubmit={submit} className="mx-auto" style={{ maxWidth: '480px' }}>
        <div className="mb-3">
          <label htmlFor="keyword-name">Name:</label>
          <input
            type="text"
            id="keyword-name"
            name="name"
            className="form-control"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="mb-3">
          <label htmlFor="only_filter" className="me-2">
            Only filter:
          </label>
          <input
            type="checkbox"
            id="only_filter"
            name="only_filter"
            className="form-check-input"
            checked={onlyFilter}
            onChange={(e) => setOnlyFilter(e.target.checked)}
          />
        </div>
        {message && (
          <div className="alert alert-success py-2" role="alert">
            {message}
          </div>
        )}
        {error && (
          <div className="alert alert-danger py-2" role="alert">
            Error: {error}
          </div>
        )}
        <button
          type="submit"
          className="btn btn-primary"
          disabled={addKeyword.isPending}
        >
          {addKeyword.isPending ? 'Adding…' : 'Add Keyword'}
        </button>
      </form>
    </div>
  );
}
