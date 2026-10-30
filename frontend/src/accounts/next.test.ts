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

  it('rejects WHATWG-parser open-redirect bypasses', () => {
    // Backslash normalizes to '/' for special schemes and
    // tab/newline bytes are stripped mid-string — all of these
    // parse as '//evil.example' to a different origin even
    // though the raw string starts with a single '/'.
    for (const next of [
      '/\\evil.example',
      '/\\\\evil.example',
      '/\t/evil.example',
      '/\n/evil.example',
    ]) {
      const search = `?next=${encodeURIComponent(next)}`;
      expect(safeNext(search), next).toBe('/');
    }
    // Percent-encoded forms decode to the same payloads.
    expect(safeNext('?next=/%5Cevil.example')).toBe('/');
    expect(safeNext('?next=/%09/evil.example')).toBe('/');
    expect(safeNext('?next=/%0a/evil.example')).toBe('/');
  });
});
