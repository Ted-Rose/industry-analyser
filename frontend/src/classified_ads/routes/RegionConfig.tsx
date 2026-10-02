import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  fetchRegionConfig,
  type Kind,
  type RegionNodeOut,
} from '../api';
import { useSaveRegionConfig } from '../mutations';
import { errorDetail } from '../../shared/api/errors';
import { useBootstrap } from '../../shared/hooks/useBootstrap';

const COPY: Record<
  Kind,
  { icon: string; label: string; syncJob: string; statsPath: string }
> = {
  apartment: {
    icon: '🏢',
    label: 'apartment',
    syncJob: 'sync-apartment-regions',
    statsPath: '/apartments/regions/stats',
  },
  house: {
    icon: '🏡',
    label: 'house',
    syncJob: 'sync-housing-regions',
    statsPath: '/houses/regions/stats',
  },
};

/**
 * React port of apartment/house_region_config.html — the scrape-enabled
 * checkbox tree. The retired view took an anonymous POST; the mutation
 * is session-authed now (401 → /admin/login/ bounce via the client),
 * so anonymous users see a hint. Parent checkboxes cascade to their
 * sub-regions, like the old inline script.
 */
export default function RegionConfig({ kind }: { kind: Kind }) {
  const { user } = useBootstrap();
  const copy = COPY[kind];

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['classified_ads', 'region-config', kind],
    queryFn: () => fetchRegionConfig(kind),
  });

  // Checked state is a Set of region URLs — the old form submitted
  // name="regions" inputs carrying value="{{ region.url }}".
  const [checked, setChecked] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!data) return;
    // Refetch after save repopulates from scrape_enabled.
    const initial = new Set<string>();
    for (const node of data.regions_tree) {
      if (node.scrape_enabled) initial.add(node.url);
      for (const sub of node.sub_regions) {
        if (sub.scrape_enabled) initial.add(sub.url);
      }
    }
    setChecked(initial);
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

  // The live numerator counts staged checkboxes (what a save would
  // enable); total_count is the DB-wide kind count — an enabled
  // region outside the rendered tree can make them diverge, so the
  // server's enabled_count is shown alongside when it disagrees.
  const enabledCount = checked.size;
  const totalCount = data?.total_count ?? 0;

  return (
    <div className="config-page">
      <div className="container">
        <Link to={copy.statsPath} className="back-link">
          View Region Stats →
        </Link>

        <h1>
          {copy.icon}{' '}
          {kind === 'apartment' ? 'Apartment' : 'House'} Region
          Configuration
        </h1>
        <p className="subtitle">
          Select which {copy.label} regions to scrape from SS.com. Run
          the <strong>{copy.syncJob}</strong> Cloud Run job to refresh
          this list from SS.com.
        </p>

        <div className="stats">
          <strong>{enabledCount}</strong> of{' '}
          <strong>{totalCount}</strong> {copy.label} regions enabled
          for scraping
          {data && data.enabled_count !== enabledCount && (
            <span className="text-muted">
              {' '}
              ({data.enabled_count} currently enabled)
            </span>
          )}
        </div>

        {!user && (
          <p className="text-muted">
            Saving requires an admin login — submitting will send you
            to the sign-in page.
          </p>
        )}

        {isError && (
          <div className="alert alert-danger" role="alert">
            Failed to load regions — {errorDetail(error)}
          </div>
        )}
        {saveError && (
          <div className="alert alert-danger py-2" role="alert">
            Error: {saveError}
          </div>
        )}

        <form onSubmit={submit}>
          <div className="region-list">
            {isPending && <p style={{ color: '#666' }}>Loading…</p>}
            {data && data.regions_tree.length === 0 && (
              <p style={{ color: '#666' }}>
                No {copy.label} regions in database yet. Run the{' '}
                <strong>{copy.syncJob}</strong> Cloud Run job to
                populate.
              </p>
            )}
            {data?.regions_tree.map((region) => (
              <div className="region-item" key={region.id}>
                <label className="parent-region">
                  <input
                    type="checkbox"
                    className="parent-checkbox"
                    checked={checked.has(region.url)}
                    onChange={(e) =>
                      toggle(region, e.target.checked)
                    }
                  />
                  {region.name}
                </label>
                {region.sub_regions.length > 0 && (
                  <div className="sub-regions">
                    {region.sub_regions.map((sub) => (
                      <div className="region-item" key={sub.id}>
                        <label className="sub-region">
                          <input
                            type="checkbox"
                            className="sub-checkbox"
                            checked={checked.has(sub.url)}
                            onChange={(e) =>
                              toggleLeaf(sub.url, e.target.checked)
                            }
                          />
                          {sub.name}
                        </label>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div className="actions">
            <button
              type="submit"
              className="btn-primary-action"
              disabled={save.isPending || isPending}
            >
              {save.isPending ? 'Saving…' : 'Save Configuration'}
            </button>
            <button
              type="button"
              className="btn-secondary-action"
              onClick={() => window.location.reload()}
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
