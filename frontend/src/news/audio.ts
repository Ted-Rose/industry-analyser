/**
 * Digest audio player — DOM-free React port of the retired
 * news/static/news/audio.js. Each item's headline and
 * description are synthesized on demand via GET
 * /api/news/audio/ (gTTS → GCS signed URL). On digest load the
 * newest digest's clips pre-warm through a bounded resolve
 * pool so playback feels instant; content-addressed clips
 * make revisits ~free. When the bucket is unconfigured
 * (local dev), the first 502 stops the fan-out and the page
 * shows "Audio unavailable"; real clicks still go through.
 *
 * DOM concerns of the old script map onto the exported
 * snapshot: `playing` drives the ■ Stop button's visibility,
 * `down` the .audio-note, and `resetSeq` bumps on a user Stop
 * so per-button transient states (⏳/⚠) reset — the old
 * `.audio-btn[data-state]` sweep.
 */
export interface ClipJob {
  /** Clip-cache key — one request per key across buttons. */
  key: string;
  text: string;
  /** 't' title clip or 'd' description clip (filename prefix). */
  kind: string;
}

export type AudioButtonState = 'loading' | 'error' | null;

export interface AudioSnapshot {
  /** A clip is queued or playing — the ■ Stop button shows. */
  playing: boolean;
  /** A 502 stopped the warm fan-out — the note shows. */
  down: boolean;
  /** Bumped by stopPlayback — buttons reset transient state. */
  resetSeq: number;
}

const ENDPOINT = '/api/news/audio/';
export const POOL_SIZE = 3;
export const MAX_TEXT = 2300;

type HttpStatusError = Error & { status?: number };

interface PoolJob extends ClipJob {
  warm: boolean;
  resolve: (url: string | null) => void;
  reject: (err: unknown) => void;
}

const cache = new Map<string, Promise<string>>();
let poolQueue: PoolJob[] = [];
let poolActive = 0;
let audioDown = false;
let playQueue: string[] = [];
let clipToken = 0;
let player: HTMLAudioElement | null = null;

let snapshot: AudioSnapshot = {
  playing: false,
  down: false,
  resetSeq: 0,
};
const listeners = new Set<() => void>();

function setSnapshot(patch: Partial<AudioSnapshot>): void {
  snapshot = { ...snapshot, ...patch };
  listeners.forEach((cb) => cb());
}

/** useSyncExternalStore-compatible subscribe. */
export function subscribeAudio(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}

/** Stable snapshot object — replaced only on state change. */
export function getAudioSnapshot(): AudioSnapshot {
  return snapshot;
}

/** djb2 hex — the server re-hashes anyway, so this only keeps
 *  filenames distinct for bucket browsing. */
export function hashText(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i += 1) {
    h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  }
  return h.toString(16);
}

function fetchAudio(text: string, kind: string): Promise<string> {
  const clipped = text.slice(0, MAX_TEXT);
  const qs =
    `?text=${encodeURIComponent(clipped)}` +
    `&filename=${encodeURIComponent(
      `${kind}-${hashText(clipped)}`,
    )}`;
  return fetch(ENDPOINT + qs).then((response) => {
    if (!response.ok) {
      const err: HttpStatusError = new Error(
        `HTTP ${response.status}`,
      );
      err.status = response.status;
      throw err;
    }
    return (response.json() as Promise<{ audio_url: string }>)
      .then((data) => data.audio_url);
  });
}

// One cache entry per clip key guarantees one request per
// clip; only successes stay cached so a click can retry.
function ensureAudio(
  key: string,
  text: string,
  kind: string,
): Promise<string> {
  let promise = cache.get(key);
  if (!promise) {
    promise = fetchAudio(text, kind).catch((err: unknown) => {
      cache.delete(key);
      throw err;
    });
    cache.set(key, promise);
  }
  return promise;
}

function pump(): void {
  while (poolActive < POOL_SIZE && poolQueue.length) {
    const job = poolQueue.shift() as PoolJob;
    poolActive += 1;
    ensureAudio(job.key, job.text, job.kind).then(
      (url) => {
        job.resolve(url);
        poolActive -= 1;
        pump();
      },
      (err: unknown) => {
        job.reject(err);
        poolActive -= 1;
        pump();
      },
    );
  }
}

function resolveClip(
  key: string,
  text: string,
  kind: string,
  warm = false,
): Promise<string | null> {
  return new Promise((resolve, reject) => {
    poolQueue.push({ key, text, kind, warm, resolve, reject });
    pump();
  });
}

// A 502 means the pipeline is down (e.g. GCS_AUDIO_BUCKET
// unset) — cancel the remaining warm jobs instead of
// hammering the endpoint. Real clicks still go through.
function cancelWarm(): void {
  audioDown = true;
  poolQueue = poolQueue.filter((job) => {
    if (job.warm) {
      job.resolve(null);
      return false;
    }
    return true;
  });
  setSnapshot({ down: true });
}

function warmClip(
  key: string,
  text: string,
  kind: string,
): Promise<string | null> {
  if (audioDown) {
    return Promise.resolve(null);
  }
  const promise = resolveClip(key, text, kind, true);
  promise.catch((err: unknown) => {
    if (
      !audioDown &&
      (err as HttpStatusError | null)?.status === 502
    ) {
      cancelWarm();
    }
  });
  return promise;
}

/** Pre-warm enqueue (no playback) — the newest digest's clips
 *  only, satisfying "generate on visit" without blocking
 *  render. */
export function warmClips(jobs: ClipJob[]): void {
  jobs.forEach((job) => {
    void warmClip(job.key, job.text, job.kind);
  });
}

/** One item = title clip then description clip (skipped when
 *  the story carries no representative lead). */
export function buttonJobs(
  id: string,
  title: string,
  desc?: string | null,
): ClipJob[] {
  const jobs: ClipJob[] = [
    { key: `${id}|t`, text: title, kind: 't' },
  ];
  if (desc) {
    jobs.push({ key: `${id}|d`, text: desc, kind: 'd' });
  }
  return jobs;
}

/** Clip jobs for one digest item — the key shares the
 *  per-item button's namespace, so ▶ item / ▶ date / ▶ all
 *  dedup on the same cache entries. */
export function itemJobs(item: {
  story_id: number;
  headline: string;
  representative_lead: string;
}): ClipJob[] {
  return buttonJobs(
    `story-${item.story_id}`,
    item.headline,
    item.representative_lead,
  );
}

/** Every item's jobs under one scope — the per-digest and
 *  play-all fan-outs. */
export function jobsForItems(
  items: {
    story_id: number;
    headline: string;
    representative_lead: string;
  }[],
): ClipJob[] {
  return items.flatMap(itemJobs);
}

function getPlayer(): HTMLAudioElement {
  if (!player) {
    player = new Audio();
    player.addEventListener('ended', playNext);
    player.addEventListener('error', () => {
      clipFailed(clipToken);
    });
  }
  return player;
}

// A failing clip trips BOTH the play() rejection and the
// element 'error' event — only the callback carrying the
// current clip's token advances, so one failure consumes
// exactly one queue entry.
function clipFailed(token: number): void {
  if (token !== clipToken) {
    return;
  }
  playNext();
}

function playNext(): void {
  const url = playQueue.shift();
  if (!url) {
    setSnapshot({ playing: false });
    return;
  }
  clipToken += 1;
  const token = clipToken;
  const element = getPlayer();
  element.src = url;
  const played = element.play();
  if (played && typeof played.catch === 'function') {
    played.catch(() => {
      clipFailed(token);
    });
  }
}

/** Internal halt — clears the queue and pauses. Does NOT bump
 *  resetSeq: startPlayback calls this mid-click and must not
 *  wipe the loading state it just set (the old script only
 *  reset button states on an explicit Stop click). */
function haltPlayback(): void {
  playQueue = [];
  if (player) {
    player.pause();
    player.removeAttribute('src');
    player.load();
  }
  if (snapshot.playing) {
    setSnapshot({ playing: false });
  }
}

/** The ■ Stop button — clears the queue and resets every
 *  button's transient state (resetSeq bump). */
export function stopPlayback(): void {
  haltPlayback();
  setSnapshot({ resetSeq: snapshot.resetSeq + 1 });
}

/** A play click replaces the current queue: resolve every
 *  clip through the pool, drop failures, play in order. */
export function startPlayback(
  jobs: ClipJob[],
  setState?: (state: AudioButtonState) => void,
): void {
  if (!jobs.length) {
    return;
  }
  setState?.('loading');
  haltPlayback();
  void Promise.allSettled(
    jobs.map((job) => resolveClip(job.key, job.text, job.kind)),
  ).then((results) => {
    const urls: string[] = [];
    results.forEach((result) => {
      if (result.status === 'fulfilled' && result.value) {
        urls.push(result.value);
      }
    });
    if (!urls.length) {
      setState?.('error');
      return;
    }
    setState?.(null);
    playQueue = urls;
    setSnapshot({ playing: true });
    playNext();
  });
}

/** Test hook — clears module state between specs (the clip
 *  cache, pool queue, latch and player are module-level). */
export function resetAudioForTests(): void {
  cache.clear();
  poolQueue = [];
  poolActive = 0;
  audioDown = false;
  playQueue = [];
  clipToken = 0;
  if (player) {
    player.pause();
    player.removeAttribute('src');
  }
  player = null;
  snapshot = { playing: false, down: false, resetSeq: 0 };
}
