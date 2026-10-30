import { describe, expect, it } from 'vitest';
import { safeNext } from './next';

describe('safeNext', () => {
  it('passes same-origin pathnames through', () => {
    expect(safeNext('?next=/dashboard/')).toBe('/dashboard/');
    expect(safeNext('?next=/vacancies/?x=1')).toBe('/vacancies/?x=1');
  });

  it('falls back to / when next is absent or empty', () => {
    expect(safeNext('')).toBe('/');
    expect(safeNext('?foo=bar')).toBe('/');
    expect(safeNext('?next=')).toBe('/');
  });

  it('rejects absolute, protocol-relative and scheme URLs', () => {
    for (const next of [
      'https://evil.example/',
      '//evil.example/',
      'javascript:alert(1)',
      'evil.example',
    ]) {
      const search = `?next=${encodeURIComponent(next)}`;
      expect(safeNext(search), next).toBe('/');
    }
  });
});
