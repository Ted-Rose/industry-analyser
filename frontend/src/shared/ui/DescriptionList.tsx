import { ReactNode } from 'react';
import { cx } from '../cx';

export interface DescriptionItem {
  term: ReactNode;
  description: ReactNode;
}

export interface DescriptionListProps {
  items: DescriptionItem[];
  className?: string;
}

/**
 * dl grid — plan §6 `ui/DescriptionList`. Replaces the
 * CompanyDetail/PropertyDetail `dl` grids: muted term column,
 * value column, single column under sm.
 */
export function DescriptionList({
  items,
  className,
}: DescriptionListProps) {
  return (
    <dl
      className={cx(
        'grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-[10rem_1fr]',
        className,
      )}
    >
      {items.map((item, index) => (
        <div key={index} className="contents">
          <dt className="text-sm font-medium text-fg-muted">
            {item.term}
          </dt>
          <dd className="min-w-0 text-sm text-fg">
            {item.description}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export default DescriptionList;
