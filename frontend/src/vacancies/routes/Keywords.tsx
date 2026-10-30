import { useState } from 'react';
import { useAddKeyword } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import { Alert } from '../../shared/ui/ErrorState';
import Button from '../../shared/ui/Button';
import Checkbox from '../../shared/ui/Checkbox';
import Field from '../../shared/ui/Field';
import Input from '../../shared/ui/Input';

/**
 * React replacement for the retired /add_keyword/ page (301'd here).
 * The old HARD_CODED_PASSWORD gate is gone — the POST is staff-authed
 * now, so non-staff users see a hint and the API client bounces
 * anonymous ones to /accounts/login/ on the 401. `only_filter` stays
 * pre-checked, as in the template form.
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
    <PageContainer width="narrow">
      <PageHeader
        back={{ to: '/vacancies', label: 'Back to Vacancies' }}
        title="Add Keyword"
      />
      {!user && (
        <Alert tone="info" className="mb-4">
          Adding a keyword requires an admin login — submitting
          will send you to the sign-in page.
        </Alert>
      )}
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name:" htmlFor="keyword-name">
          <Input
            type="text"
            id="keyword-name"
            name="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Checkbox
          id="only_filter"
          name="only_filter"
          label="Only filter:"
          checked={onlyFilter}
          onChange={(e) => setOnlyFilter(e.target.checked)}
        />
        {message && <Alert tone="success">{message}</Alert>}
        {error && (
          <Alert tone="danger">Error: {error}</Alert>
        )}
        <div className="flex justify-end">
          <Button type="submit" loading={addKeyword.isPending}>
            Add Keyword
          </Button>
        </div>
      </form>
    </PageContainer>
  );
}
