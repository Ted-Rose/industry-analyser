import { describe, expect, it } from 'vitest';
import { formatDateTime, formatDuration } from './format';

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

describe('formatDuration', () => {
  it('renders str(timedelta)-ish H:MM:SS under a day', () => {
    expect(formatDuration(0)).toBe('0:00:00');
    expect(formatDuration(323)).toBe('0:05:23');
    expect(formatDuration(3723)).toBe('1:02:03');
  });

  it('prefixes whole days', () => {
    expect(formatDuration(90000)).toBe('1d 1:00:00');
  });

  it('returns the em dash for null', () => {
    expect(formatDuration(null)).toBe('—');
  });
});
