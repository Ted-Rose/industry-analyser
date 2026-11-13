import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from './App';

// Route components stubbed — the assertion targets App's
// route table, not the pages' query/fetch behavior.
vi.mock('./routes/DigestList', () => ({
  default: () => <div>digest-list-stub</div>,
}));
vi.mock('./routes/DigestDetail', () => ({
  default: () => <div>digest-detail-stub</div>,
}));
vi.mock('./routes/Preferences', () => ({
  default: () => <div>preferences-stub</div>,
}));

function renderAt(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <App />
    </MemoryRouter>,
  );
}

describe('App routes', () => {
  it('redirects the retired /audio endpoint to the index', () => {
    renderAt('/audio');
    expect(screen.getByText('digest-list-stub')).toBeDefined();
    expect(screen.queryByText('digest-detail-stub')).toBeNull();
  });

  it('routes a date-shaped segment to the digest detail', () => {
    renderAt('/2026-10-29');
    expect(screen.getByText('digest-detail-stub')).toBeDefined();
  });

  it('falls back to the index for unknown paths', () => {
    renderAt('/story/12/fragment/');
    expect(screen.getByText('digest-list-stub')).toBeDefined();
  });
});
