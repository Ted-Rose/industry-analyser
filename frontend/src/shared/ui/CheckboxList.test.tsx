import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import CheckboxList from './CheckboxList';

const OPTIONS = [
  { value: 'it', label: 'IT' },
  { value: 'finance', label: 'Finance' },
  { value: 'logistics', label: 'Logistics' },
];

function Harness({ searchable = false }) {
  const [value, setValue] = useState<string[]>(['it']);
  return (
    <div>
      <output data-testid="value">{value.join(',')}</output>
      <CheckboxList
        options={OPTIONS}
        value={value}
        onChange={setValue}
        searchable={searchable}
      />
    </div>
  );
}

describe('CheckboxList', () => {
  it('toggles options and reports "n selected"', () => {
    render(<Harness />);
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    expect(screen.getByTestId('value')).toHaveTextContent('it');

    fireEvent.click(screen.getByLabelText('Finance'));
    expect(screen.getByTestId('value'))
      .toHaveTextContent('it,finance');
    expect(screen.getByText('2 selected')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('IT'));
    expect(screen.getByTestId('value'))
      .toHaveTextContent('finance');
    expect(screen.getByText('1 selected')).toBeInTheDocument();
  });

  it('filters options through the search input', () => {
    render(<Harness searchable />);
    const search = screen.getByRole('searchbox', {
      name: 'Search…',
    });
    fireEvent.change(search, { target: { value: 'log' } });
    expect(screen.getByLabelText('Logistics')).toBeInTheDocument();
    expect(screen.queryByLabelText('IT')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Finance'))
      .not.toBeInTheDocument();
    // Selection count still reflects the full value.
    expect(screen.getByText('1 selected')).toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'zzz' } });
    expect(screen.getByText('No matches.')).toBeInTheDocument();
  });
});
