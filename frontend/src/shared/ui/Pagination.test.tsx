import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import Pagination from './Pagination';

/** Shows the live query string so tests can assert navigation. */
function PageEcho() {
  const [params] = useSearchParams();
  return (
    <output data-testid="page">
      {params.toString() || '(empty)'}
    </output>
  );
}

function renderPagination(entry: string, props = {}) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Pagination page={2} numPages={7} {...props} />
      <PageEcho />
    </MemoryRouter>,
  );
}

describe('Pagination', () => {
  it('renders nothing for a single page', () => {
    const { container } = render(
      <MemoryRouter>
        <Pagination page={1} numPages={1} />
      </MemoryRouter>,
    );
    expect(
      container.querySelector('[aria-label="Page navigation"]'),
    ).not.toBeInTheDocument();
  });

  it('navigates via the numbered window and writes ?page=', () => {
    renderPagination('/?page=2&q=x');
    const nav = screen.getByRole('navigation', {
      name: 'Page navigation',
    });
    // ≥sm variant: numbered window ±2 around page 2 → 1–4,
    // current rendered as an aria-current span.
    expect(nav).toHaveTextContent('1234');
    expect(nav.querySelector('[aria-current="page"]'))
      .toHaveTextContent('2');
    // Compact <sm variant shows "n / m".
    expect(nav).toHaveTextContent('2 / 7');
    // No « » first/last controls anywhere (§8.13).
    expect(
      screen.queryByRole('button', { name: 'First page' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Last page' }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', {
      name: 'Next page',
    })[0]);
    // page=3 written, other params survive.
    expect(screen.getByTestId('page')).toHaveTextContent('page=3');
    expect(screen.getByTestId('page')).toHaveTextContent('q=x');
  });

  it('deletes ?page when navigating back to page 1', () => {
    renderPagination('/?page=2');
    fireEvent.click(screen.getAllByRole('button', {
      name: 'Previous page',
    })[0]);
    expect(screen.getByTestId('page')).toHaveTextContent('(empty)');
  });

  it('uses onPageChange instead of the URL when provided', () => {
    let seen = 0;
    renderPagination('/?page=2', {
      onPageChange: (n: number) => {
        seen = n;
      },
    });
    fireEvent.click(screen.getAllByRole('button', {
      name: 'Page 4',
    })[0]);
    expect(seen).toBe(4);
    expect(screen.getByTestId('page')).toHaveTextContent('page=2');
  });

  it('renders the optional summary line', () => {
    renderPagination('/?page=2', {
      summary: 'Showing 51–100 of 680',
    });
    expect(
      screen.getByText('Showing 51–100 of 680'),
    ).toBeInTheDocument();
  });
});
