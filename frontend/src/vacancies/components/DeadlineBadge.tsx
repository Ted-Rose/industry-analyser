import { deadlineClass, formatDate } from '../format';
import Badge from '../../shared/ui/Badge';

/**
 * Deadline cells — deadline-past red, deadline-active green,
 * mirroring `{% if vacancy.application_deadline < now %}`.
 */
export default function DeadlineBadge({
  deadline,
  now,
}: {
  deadline?: string | null;
  now: Date;
}) {
  if (!deadline) return <>—</>;
  const cls = deadlineClass(deadline, now);
  if (cls === '') return <>{formatDate(deadline)}</>;
  return (
    <Badge tone={cls === 'deadline-past' ? 'danger' : 'success'}>
      {formatDate(deadline)}
    </Badge>
  );
}
