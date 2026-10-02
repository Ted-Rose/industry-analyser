import type { Kind } from './api';

/** In-SPA path builders per kind — the /apartments/… ↔ /houses/…
 *  route prefixes mirror the old URL names. */
export function kindUrls(kind: Kind) {
  const base = kind === 'apartment' ? '/apartments' : '/houses';
  return {
    config: `${base}/regions/config`,
    stats: `${base}/regions/stats`,
    statsChildren: (regionId: number) =>
      `${base}/regions/stats/${regionId}/children`,
    regionAds: (regionId: number) => `${base}/regions/${regionId}/ads`,
    properties: `/properties/${
      kind === 'apartment' ? 'apartments' : 'houses'
    }`,
    property: (pk: number) =>
      `/properties/${
        kind === 'apartment' ? 'apartments' : 'houses'
      }/${pk}`,
  };
}
