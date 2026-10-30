import { ExternalLink } from 'lucide-react';
import Badge from '../../shared/ui/Badge';
import type { CompanyIdentityOut } from '../api';

/**
 * Portal-identity pill (`cv.lv:66466`). Links to the employer's
 * public vacancy search on the source portal when the API knows a
 * URL for it — cv.lv has no public employer profile page, so the
 * search URL is the closest public "company page".
 */
export default function IdentityTag({
  identity,
}: {
  identity: CompanyIdentityOut;
}) {
  const label = `${identity.source}:${identity.employer_id}`;
  if (!identity.portal_url) {
    return <Badge tone="accent">{label}</Badge>;
  }
  return (
    <Badge
      tone="accent"
      href={identity.portal_url}
      target="_blank"
      rel="noopener"
    >
      {label}
      <ExternalLink className="size-3" aria-hidden="true" />
    </Badge>
  );
}
