import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import FilterBar from './FilterBar';
import Field from './Field';
import Input from './Input';

describe('FilterBar', () => {
  it('submits via Apply after preventDefault', () => {
    const onSubmit = vi.fn();
    render(
      <FilterBar onSubmit={onSubmit}>
        <Field label="Search" htmlFor="q">
          <Input id="q" />
        </Field>
      </FilterBar>,
    );
    const form = screen.getByRole('search', { name: 'Filters' });
    fireEvent.submit(form);
    expect(onSubmit).toHaveBeenCalledTimes(1);
    // The Button's type=submit path reaches the same handler.
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it('renders a ghost Reset only when onReset is set', () => {
    const onReset = vi.fn();
    const { unmount } = render(
      <FilterBar onSubmit={() => {}} onReset={onReset}>
        <span />
      </FilterBar>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(onReset).toHaveBeenCalledTimes(1);
    unmount();
    render(
      <FilterBar onSubmit={() => {}}>
        <span />
      </FilterBar>,
    );
    expect(
      screen.queryByRole('button', { name: 'Reset' }),
    ).not.toBeInTheDocument();
  });

  it('collapsible="mobile" toggles a "Filters (n)" button', () => {
    render(
      <FilterBar
        onSubmit={() => {}}
        collapsible="mobile"
        activeCount={2}
      >
        <span data-testid="field" />
      </FilterBar>,
    );
    const toggle = screen.getByRole('button', {
      name: 'Filters (2)',
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    // Region starts hidden below md (md:grid keeps ≥md open).
    const region = document.getElementById(
      toggle.getAttribute('aria-controls') ?? '',
    );
    expect(region).toHaveClass('hidden', 'md:grid');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(region).toHaveClass('grid', 'md:grid');
    expect(region).not.toHaveClass('hidden');
  });

  it('collapsible="always" hides the region until opened', () => {
    render(
      <FilterBar onSubmit={() => {}} collapsible="always">
        <span data-testid="field" />
      </FilterBar>,
    );
    const toggle = screen.getByRole('button', { name: 'Filters' });
    const region = document.getElementById(
      toggle.getAttribute('aria-controls') ?? '',
    );
    expect(region).toHaveClass('hidden');
    expect(region).not.toHaveClass('md:grid');
  });
});
