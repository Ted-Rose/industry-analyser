import type { ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  within,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DataTable, { type Column } from './DataTable';

interface Row {
  id: number;
  name: string;
  price: number;
}

const ROWS: Row[] = [
  { id: 1, name: 'Banana', price: 2 },
  { id: 2, name: 'Apple', price: 10 },
  { id: 3, name: 'Cherry', price: 5 },
];

const COLUMNS: Column<Row>[] = [
  {
    id: 'name',
    header: 'Name',
    cell: (row) => row.name,
    sortable: true,
    mobile: 'title',
  },
  {
    id: 'price',
    header: 'Price',
    cell: (row) => row.price,
    align: 'right',
    sortable: true,
    sortValue: (row) => row.price,
  },
];

function renderTable(ui: ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function tableCellOrder(): string[] {
  return screen
    .getAllByRole('cell')
    .map((cell) => cell.textContent ?? '')
    .filter((text) => ['Apple', 'Banana', 'Cherry'].includes(text));
}

describe('DataTable', () => {
  it('client-sorts rows when a sortable header is clicked', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS}
        getRowKey={(row) => row.id}
        caption="Fruit"
      />,
    );
    // Unsorted: rows render in given order.
    expect(tableCellOrder()).toEqual([
      'Banana',
      'Apple',
      'Cherry',
    ]);

    fireEvent.click(screen.getByRole('button', { name: /Name/ }));
    expect(tableCellOrder()).toEqual([
      'Apple',
      'Banana',
      'Cherry',
    ]);
    expect(
      screen.getByRole('columnheader', { name: /Name/ }),
    ).toHaveAttribute('aria-sort', 'ascending');

    fireEvent.click(screen.getByRole('button', { name: /Name/ }));
    expect(tableCellOrder()).toEqual([
      'Cherry',
      'Banana',
      'Apple',
    ]);
    expect(
      screen.getByRole('columnheader', { name: /Name/ }),
    ).toHaveAttribute('aria-sort', 'descending');
  });

  it('keeps caller order in controlled sortMode', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS}
        getRowKey={(row) => row.id}
        sort={{ id: 'name', dir: 'desc' }}
        sortMode="controlled"
        caption="Fruit"
      />,
    );
    expect(tableCellOrder()).toEqual([
      'Banana',
      'Apple',
      'Cherry',
    ]);
  });

  it('expands a detail row via the chevron with aria-expanded', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 1)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        renderExpanded={(row) => `Details for ${row.name}`}
      />,
    );
    const toggle = screen.getAllByRole('button', {
      name: 'Expand row',
    })[0];
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // The expanded content renders twice by design — the colSpan
    // table row and inside the mobile card below the slots.
    const details = screen.getAllByText('Details for Banana');
    expect(details.length).toBe(2);
    const detailCell = details
      .map((el) => el.closest('td'))
      .find((td) => td !== null);
    expect(detailCell).toHaveAttribute('colspan', '3');
  });

  it('renders no expand affordance on rows hasExpanded ' +
    'rejects', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 2)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        renderExpanded={(row) => `Details for ${row.name}`}
        hasExpanded={(row) => row.id === 1}
      />,
    );
    // Two rows, one expandable: one desktop chevron + one
    // mobile "Details" toggle — the rejected row gets an
    // empty chevron cell and no card toggle.
    expect(
      screen.getAllByRole('button', { name: 'Expand row' }),
    ).toHaveLength(1);
    expect(
      screen.getAllByRole('button', { name: 'Details' }),
    ).toHaveLength(1);
  });

  it('pins the chevron column at left-0 and the first data ' +
    'column at left-10 with stickyFirstColumn', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 1)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        mobile="scroll"
        stickyFirstColumn
        renderExpanded={(row) => `Details for ${row.name}`}
      />,
    );
    const headers = screen.getAllByRole('columnheader');
    // [chevron, Name, Price] — the chevron pins at the edge,
    // the first data column beside it at the w-10 offset.
    expect(headers[0]).toHaveClass('sticky', 'left-0', 'z-30');
    expect(headers[1]).toHaveClass('sticky', 'left-10', 'z-20');
    const cells = screen.getAllByRole('cell');
    expect(cells[0]).toHaveClass('sticky', 'left-0');
    expect(cells[1]).toHaveClass('sticky', 'left-10');
  });

  it('opens rowHref in a new tab on middle-click', () => {
    const open = vi
      .spyOn(window, 'open')
      .mockImplementation(() => null);
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 1)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        rowHref={(row) => `/rows/${row.id}`}
      />,
    );
    const row = screen.getAllByRole('link')[0];
    // No named auxclick in this @testing-library/dom's event
    // map — dispatch the raw middle-click event instead.
    fireEvent(
      row,
      new MouseEvent('auxclick', {
        bubbles: true,
        cancelable: true,
        button: 1,
      }),
    );
    expect(open).toHaveBeenCalledWith(
      '/rows/1',
      '_blank',
      'noopener',
    );
    open.mockRestore();
  });

  it('renders mobile cards under mobile="cards"', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 1)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        mobile="cards"
      />,
    );
    // Card list mirrors the row — 'Name' cell lands in the
    // title slot of the generated card.
    const list = screen.getByRole('list');
    expect(within(list).getByText('Banana')).toBeInTheDocument();
    // The table wrapper is the desktop-only sibling.
    const table = screen.getByRole('table', { name: 'Fruit' });
    expect(table.parentElement).toHaveClass('hidden', 'md:block');
  });

  it('renders a scroll container and no cards under ' +
    'mobile="scroll"', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={ROWS.slice(0, 1)}
        getRowKey={(row) => row.id}
        caption="Fruit"
        mobile="scroll"
        stickyFirstColumn
      />,
    );
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    const table = screen.getByRole('table', { name: 'Fruit' });
    expect(table.parentElement).toHaveClass('overflow-x-auto');
  });

  it('renders the empty state and honors caption + footer', () => {
    renderTable(
      <DataTable
        columns={COLUMNS}
        rows={[]}
        getRowKey={(row) => row.id}
        caption="Fruit"
        empty={<p>Nothing here.</p>}
        footer={
          <tr>
            <td>Total</td>
          </tr>
        }
      />,
    );
    expect(
      screen.getAllByText('Nothing here.').length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Total')).toBeInTheDocument();
    expect(
      screen.getByRole('table', { name: 'Fruit' }),
    ).toBeInTheDocument();
  });
});
