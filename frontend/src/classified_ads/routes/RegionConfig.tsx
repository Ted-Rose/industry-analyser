import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionConfig,
  type Kind,
  type RegionConfigOut,
  type RegionNodeOut,
} from '../api';
import { useSaveRegionConfig } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Button from '../../shared/ui/Button';
import Card from '../../shared/ui/Card';
import Checkbox from '../../shared/ui/Checkbox';
import Disclosure from '../../shared/ui/Disclosure';
import EmptyState from '../../shared/ui/EmptyState';
import ErrorState, { Alert } from '../../shared/ui/ErrorState';
import { LoadingState } from '../../shared/ui/Skeleton';

const COPY: Record<
  Kind,
  { label: string; syncJob: string; statsPath: string }
> = {
  apartment: {
    label: 'apartment',
    syncJob: 'sync-apartment-regions',
    statsPath: '/apartments/regions/stats',
  },
  house: {
    label: 'house',
    syncJob: 'sync-housing-regions',
    statsPath: '/houses/regions/stats',
  },
};

/** The scrape-enabled set the form starts from — shared by the
 *  hydrate-on-load effect and the Cancel reset. */
function enabledSet(data: RegionConfigOut | undefined) {
  const initial = new Set<string>();
  if (!data) return initial;
  for (const node of data.regions_tree) {
    if (node.scrape_enabled) initial.add(node.url);
    for (const sub of node.sub_regions) {
      if (sub.scrape_enabled) initial.add(sub.url);
    }
  }
  return initial;
}

/**
 * One parent region + its sub-region checkboxes — a
 * Disclosure+Checkbox composite kept app-local (plan §9.8). The
 * parent box mirrors the sub-region state: fully checked when
 * the parent and every sub are on, the dash (indeterminate) on
 * any partial mix.
 */
function RegionBranch({
  node,
  checked,
  onToggle,
  onToggleLeaf,
}: {
  node: RegionNodeOut;
  checked: Set<string>;
  onToggle: (node: RegionNodeOut, on: boolean) => void;
  onToggleLeaf: (url: string, on: boolean) => void;
}) {
  const allOn =
    checked.has(node.url) &&
    node.sub_regions.every((sub) => checked.has(sub.url));
  const anyOn =
    checked.has(node.url) ||
    node.sub_regions.some((sub) => checked.has(sub.url));
  if (node.sub_regions.length === 0) {
    return (
      <div className="py-0.5">
        <Checkbox
          label={node.name}
          checked={checked.has(node.url)}
          onChange={(e) => onToggle(node, e.target.checked)}
        />
      </div>
    );
  }
  const box = (
    <span
      onClick={(e) => {
        // Any click inside <summary> toggles the <details> —
        // swallow the native default (the input's own flip and
        // the label→input forward included) and drive the whole
        // cascade from React state instead.
        e.preventDefault();
        onToggle(node, !allOn);
      }}
    >
      <Checkbox
        label={node.name}
        checked={allOn}
        indeterminate={anyOn && !allOn}
        // readOnly silences the controlled-input warning —
        // onChange never fires once the click is cancelled.
        readOnly
      />
    </span>
  );
  return (
    <Disclosure defaultOpen summary={box}>
      <div className="flex flex-col gap-1.5 py-1">
        {node.sub_regions.map((sub) => (
          <Checkbox
            key={sub.id}
            label={sub.name}
            checked={checked.has(sub.url)}
            onChange={(e) =>
              onToggleLeaf(sub.url, e.target.checked)
            }
          />
        ))}
      </div>
    </Disclosure>
  );
}

/**
 * React port of apartment/house_region_config.html — the
 * scrape-enabled checkbox tree. The retired view took an
 * anonymous POST; the mutation is session-authed now (401 →
 * /admin/login/ bounce via the client), so anonymous users see a
 * hint. Parent checkboxes cascade to their sub-regions, like the
 * old inline script.
 */
export default function RegionConfig({ kind }: { kind: Kind }) {
  const { user } = useBootstrap();
  const copy = COPY[kind];

  const { data, isPending, isError, error, refetch } = useQuery({
    queryKey: ['classified_ads', 'region-config', kind],
    queryFn: () => fetchRegionConfig(kind),
  });

  // Checked state is a Set of region URLs — the old form submitted
  // name="regions" inputs carrying value="{{ region.url }}".
  const [checked, setChecked] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!data) return;
    // Refetch after save repopulates from scrape_enabled.
    setChecked(enabledSet(data));
  }, [data]);

  const save = useSaveRegionConfig(kind);
  const [saveError, setSaveError] = useState('');

  const toggle = (node: RegionNodeOut, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(node.url);
      else next.delete(node.url);
      // Parent toggles cascade to every sub-region — the same
      // behavior the retired inline script had.
      for (const sub of node.sub_regions) {
        if (on) next.add(sub.url);
        else next.delete(sub.url);
      }
      return next;
    });
  };

  const toggleLeaf = (url: string, on: boolean) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (on) next.add(url);
      else next.delete(url);
      return next;
    });
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaveError('');
    save.mutate(
      { regions: [...checked] },
      { onError: (err) => setSaveError(errorDetail(err)) },
    );
  };

  // Cancel restores the saved state — no reload round-trip.
  const cancel = () => {
    setSaveError('');
    save.reset();
    setChecked(enabledSet(data));
  };

  // The live numerator counts staged checkboxes (what a save would
  // enable); total_count is the DB-wide kind count — an enabled
  // region outside the rendered tree can make them diverge, so the
  // server's enabled_count is shown alongside when it disagrees.
  const enabledCount = checked.size;
  const totalCount = data?.total_count ?? 0;

  return (
    <PageContainer width="narrow">
      <PageHeader
        title={`${
          kind === 'apartment' ? 'Apartment' : 'House'
        } Region Configuration`}
        description={
          <>
            Select which {copy.label} regions to scrape from
            SS.com. Run the <strong>{copy.syncJob}</strong> Cloud
            Run job to refresh this list from SS.com.
          </>
        }
        actions={
          <Button
            as={Link}
            to={copy.statsPath}
            variant="secondary"
          >
            View Region Stats
          </Button>
        }
      />

      <p className="mb-4 text-sm text-fg-muted">
        <strong className="text-fg">{enabledCount}</strong> of{' '}
        <strong className="text-fg">{totalCount}</strong>{' '}
        {copy.label} regions enabled for scraping
        {data && data.enabled_count !== enabledCount && (
          <span>
            {' '}
            ({data.enabled_count} currently enabled)
          </span>
        )}
      </p>

      {!user && (
        <p className="mb-4 text-sm text-fg-muted">
          Saving requires an admin login — submitting will send
          you to the sign-in page.
        </p>
      )}

      {saveError && (
        <Alert tone="danger" className="mb-4">
          Error: {saveError}
        </Alert>
      )}

      {isError && !data ? (
        <ErrorState
          title="Failed to load regions"
          error={errorDetail(error)}
          onRetry={() => void refetch()}
        />
      ) : (
        <form onSubmit={submit}>
          <Card className="space-y-2">
            {isPending ? (
              <LoadingState variant="cards" rows={4} />
            ) : data && data.regions_tree.length === 0 ? (
              <EmptyState
                title={`No ${copy.label} regions in database yet.`}
                description={
                  `Run the ${copy.syncJob} Cloud Run ` +
                  'job to populate.'
                }
              />
            ) : (
              data?.regions_tree.map((region) => (
                <RegionBranch
                  key={region.id}
                  node={region}
                  checked={checked}
                  onToggle={toggle}
                  onToggleLeaf={toggleLeaf}
                />
              ))
            )}
          </Card>

          <div className="mt-4 flex justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={cancel}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              loading={save.isPending}
              disabled={isPending}
            >
              Save Configuration
            </Button>
          </div>
        </form>
      )}
    </PageContainer>
  );
}
