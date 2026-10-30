import { describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { setTheme } from '../theme';
import ThemeToggle from './ThemeToggle';

describe('ThemeToggle', () => {
  it('tracks theme changes made outside the component', async () => {
    render(<ThemeToggle />);
    expect(
      screen.getByRole('button', { name: 'Theme: auto' }),
    ).toBeInTheDocument();
    // Simulates the admin toggle / another source writing the
    // same localStorage key via theme.ts — the label must
    // follow without a click on this button.
    act(() => setTheme('dark'));
    expect(
      await screen.findByRole('button', { name: 'Theme: dark' }),
    ).toBeInTheDocument();
    act(() => setTheme('auto'));
  });
});
