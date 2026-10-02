import { describe, expect, it } from 'vitest';
import { formatDateTime, formatDay, formatDuration } from './format';

describe('formatDateTime', () => {
  it('formats an ISO datetime as UTC Y-m-d H:i', () => {
    expect(formatDateTime('2026-01-05T14:37:42Z')).toBe(
      '2026-01-05 14:37',
    );
  });

  it('returns the em dash for null/invalid', () => {
    expect(formatDateTime(null)).toBe('—');
    expect(formatDateTime('not a date')).toBe('—');
  });
});

describe('formatDay', () => {
  it("formats an ISO day as Django's 'N j, Y'", () => {
    expect(formatDay('2026-01-05')).toBe('Jan. 5, 2026');
    // AP-style months: June/July spelled out, 'Sept.' for September.
    expect(formatDay('2026-06-09')).toBe('June 9, 2026');
    expect(formatDay('2026-09-30')).toBe('Sept. 30, 2026');
  });

  it('returns the em dash for null/invalid', () => {
    expect(formatDay(null)).toBe('—');
    expect(formatDay('bogus')).toBe('—');
  });
});

describe('formatDuration', () => {
  it('renders str(timedelta) H:MM:SS under a day', () => {
    expect(formatDuration(0)).toBe('0:00:00');
    expect(formatDuration(323)).toBe('0:05:23');
    expect(formatDuration(3723)).toBe('1:02:03');
  });

  it('prefixes whole days str(timedelta)-style', () => {
    expect(formatDuration(90000)).toBe('1 day, 1:00:00');
    expect(formatDuration(90000 * 2)).toBe('2 days, 2:00:00');
  });

  it('returns the em dash for null', () => {
    expect(formatDuration(null)).toBe('—');
  });
});
