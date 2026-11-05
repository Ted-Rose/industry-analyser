import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  buttonJobs,
  getAudioSnapshot,
  hashText,
  itemJobs,
  jobsForItems,
  MAX_TEXT,
  POOL_SIZE,
  resetAudioForTests,
  startPlayback,
  warmClips,
} from './audio';

type Deferred<T> = {
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
  promise: Promise<T>;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { resolve, reject, promise };
}

const mockFetch = vi.fn();

function okResponse(url = 'https://signed.example/clip.mp3') {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve({ audio_url: url }),
  };
}

/** Let the promise chain settle — pool jobs resolve through
 *  several .then hops. */
async function flush(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/** The `text` param the audio endpoint was called with. */
function calledText(call = 0): string {
  const url = String(mockFetch.mock.calls[call][0]);
  return new URLSearchParams(url.split('?')[1]).get('text') ?? '';
}

beforeEach(() => {
  resetAudioForTests();
  mockFetch.mockReset();
  vi.stubGlobal('fetch', mockFetch);
});

describe('hashText', () => {
  it('is the djb2 hex the old script produced', () => {
    // h = 5381; empty input stays at the seed.
    expect(hashText('')).toBe('1505');
    expect(hashText('a')).toBe('2b606');
  });

  it('is deterministic and input-sensitive', () => {
    expect(hashText('Ziņa viens')).toBe(hashText('Ziņa viens'));
    expect(hashText('Ziņa viens')).not.toBe(
      hashText('Ziņa divi'),
    );
  });
});

describe('buttonJobs', () => {
  it('yields a title clip only when there is no lead', () => {
    expect(buttonJobs('story-1', 'Virsraksts')).toEqual([
      { key: 'story-1|t', text: 'Virsraksts', kind: 't' },
    ]);
    expect(buttonJobs('story-1', 'Virsraksts', '')).toHaveLength(
      1,
    );
  });

  it('yields title then description clips', () => {
    expect(
      buttonJobs('story-1', 'Virsraksts', 'Apraksts'),
    ).toEqual([
      { key: 'story-1|t', text: 'Virsraksts', kind: 't' },
      { key: 'story-1|d', text: 'Apraksts', kind: 'd' },
    ]);
  });
});

describe('jobsForItems', () => {
  it('batches every item title+desc clip in order', () => {
    const jobs = jobsForItems([
      {
        story_id: 1,
        headline: 'Pirmā',
        representative_lead: 'Apraksts 1',
      },
      {
        story_id: 2,
        headline: 'Otrā',
        representative_lead: '',
      },
    ]);
    expect(jobs.map((job) => job.key)).toEqual([
      'story-1|t',
      'story-1|d',
      'story-2|t',
    ]);
  });

  it('itemJobs shares the per-item key namespace', () => {
    expect(itemJobs({
      story_id: 7,
      headline: 'H',
      representative_lead: 'D',
    })).toEqual(buttonJobs('story-7', 'H', 'D'));
  });
});

describe('clip requests', () => {
  it('clips text at MAX_TEXT before fetching', async () => {
    mockFetch.mockResolvedValue(okResponse());
    startPlayback(
      buttonJobs('s1', 'x'.repeat(MAX_TEXT + 100)),
      () => {},
    );
    await flush();
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(calledText()).toHaveLength(MAX_TEXT);
  });

  it('sends one request per clip key (cache dedup)', async () => {
    mockFetch.mockResolvedValue(okResponse());
    warmClips(buttonJobs('s1', 'T', 'D'));
    await flush();
    warmClips(buttonJobs('s1', 'T', 'D'));
    await flush();
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});

describe('resolve pool', () => {
  it('keeps at most POOL_SIZE fetches in flight', async () => {
    const pending: Deferred<unknown>[] = [];
    mockFetch.mockImplementation(() => {
      const d = deferred<unknown>();
      pending.push(d);
      return d.promise;
    });
    warmClips(
      jobsForItems([
        { story_id: 1, headline: 'a', representative_lead: 'b' },
        { story_id: 2, headline: 'c', representative_lead: 'd' },
        { story_id: 3, headline: 'e', representative_lead: '' },
      ]),
    );
    // 5 clip jobs total — only POOL_SIZE resolve at once.
    expect(mockFetch).toHaveBeenCalledTimes(POOL_SIZE);
    pending[0].resolve(okResponse('u1'));
    await flush();
    expect(mockFetch).toHaveBeenCalledTimes(POOL_SIZE + 1);
    pending.forEach((d) => d.resolve(okResponse('u')));
    await flush();
    expect(mockFetch).toHaveBeenCalledTimes(5);
  });
});

describe('502 warm-cancel latch', () => {
  it('cancels queued warm jobs on the first 502 and stays down',
    async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 502,
        json: () => Promise.resolve({}),
      });
      // Seven warm jobs — three in flight, four queued.
      warmClips(
        jobsForItems([
          {
            story_id: 1,
            headline: 'a',
            representative_lead: 'b',
          },
          {
            story_id: 2,
            headline: 'c',
            representative_lead: 'd',
          },
          {
            story_id: 3,
            headline: 'e',
            representative_lead: 'f',
          },
          {
            story_id: 4,
            headline: 'g',
            representative_lead: '',
          },
        ]),
      );
      await flush();
      expect(getAudioSnapshot().down).toBe(true);
      // The first rejection wave is dequeue-before-cancel
      // (the old script's ordering — each failed slot's
      // pump() runs before the latch's catch), so the three
      // first failures each start one more job; the seventh
      // is cancelled still queued → 6 fetches.
      expect(mockFetch).toHaveBeenCalledTimes(POOL_SIZE * 2);
      // The latch persists: further warm jobs resolve null
      // without hitting the endpoint.
      warmClips(buttonJobs('later', 'x'));
      await flush();
      expect(mockFetch).toHaveBeenCalledTimes(POOL_SIZE * 2);
    });

  it('real clicks still go through while the latch is down',
    async () => {
      mockFetch
        .mockResolvedValueOnce({ ok: false, status: 502 })
        .mockResolvedValue(okResponse());
      warmClips(buttonJobs('s1', 'warm'));
      await flush();
      expect(getAudioSnapshot().down).toBe(true);
      const states: (string | null)[] = [];
      startPlayback(buttonJobs('s2', 'click'), (s) =>
        states.push(s),
      );
      await flush();
      // The click's clip fetch ran despite the warm latch.
      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(states).toContain('loading');
      expect(states[states.length - 1]).toBeNull();
    });
});
