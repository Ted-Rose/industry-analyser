import Button from '../../shared/ui/Button';
import Field from '../../shared/ui/Field';
import Input from '../../shared/ui/Input';
import SegmentedControl from '../../shared/ui/SegmentedControl';

export type DigestPeriod = 'day' | 'week' | 'all';

const PERIOD_OPTIONS = [
  { value: 'day' as const, label: 'Diena' },
  { value: 'week' as const, label: '7 dienas' },
  { value: 'all' as const, label: 'Visi' },
];

export interface DigestFilterProps {
  /** The date input's current value (Y-m-d or ''). */
  date: string;
  period: DigestPeriod;
  /** date-input bounds — first/last digest in the DB. */
  minDate: string;
  maxDate: string;
  /** Apply a new filter state — the old form's submit. */
  onApply: (date: string, period: DigestPeriod) => void;
}

/**
 * The digest filter — React port of the GET form + filter.js
 * auto-submit: date and period changes apply immediately to
 * the URL (filter.js's requestSubmit behavior), and the
 * "Rādīt" submit button stays like the old no-JS path. Bound
 * by the server's effective values (anchor_date / period /
 * min_date / max_date echo).
 */
export default function DigestFilter({
  date,
  period,
  minDate,
  maxDate,
  onApply,
}: DigestFilterProps) {
  return (
    <form
      className="digest-filter mb-4 flex flex-wrap items-end
        gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        onApply(date, period);
      }}
    >
      <Field label="Datums" htmlFor="id_digest_date">
        <Input
          type="date"
          id="id_digest_date"
          name="date"
          value={date}
          min={minDate}
          max={maxDate}
          onChange={(event) => onApply(event.target.value, period)}
        />
      </Field>
      {/* No htmlFor — the SegmentedControl is a role=radio
          group labelled by its own ariaLabel; no element owns
          a digest-period id. */}
      <Field label="Periods">
        <SegmentedControl
          ariaLabel="Periods"
          value={period}
          options={PERIOD_OPTIONS}
          onChange={(next) => onApply(date, next)}
        />
      </Field>
      <Button type="submit" variant="secondary">
        Rādīt
      </Button>
    </form>
  );
}
