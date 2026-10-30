import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { useConfirm, usePrompt } from './Dialog';

function ConfirmHarness() {
  const { confirm, confirmElement } = useConfirm();
  const [result, setResult] = useState('unset');
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          void confirm({
            title: 'Delete filter?',
            body: 'This cannot be undone.',
            confirmLabel: 'Delete',
            danger: true,
          }).then((value) => setResult(String(value)));
        }}
      >
        Ask
      </button>
      <output data-testid="result">{result}</output>
      {confirmElement}
    </div>
  );
}

function PromptHarness() {
  const { prompt, promptElement } = usePrompt();
  const [result, setResult] = useState('unset');
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          void prompt({
            title: 'Name the filter',
            label: 'Name',
            defaultValue: 'My filter',
          }).then((value) => setResult(String(value)));
        }}
      >
        Ask
      </button>
      <output data-testid="result">{result}</output>
      {promptElement}
    </div>
  );
}

describe('useConfirm', () => {
  it('settles pending promises on replace and unmount', async () => {
    const results: boolean[] = [];
    function Host() {
      const { confirm, confirmElement } = useConfirm();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              void confirm({ title: 'Sure?' }).then((value) =>
                results.push(value),
              );
            }}
          >
            Ask
          </button>
          {confirmElement}
        </div>
      );
    }
    const view = render(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await screen.findByText('Sure?');
    // A second confirm() while open resolves the first as
    // cancelled instead of orphaning its promise.
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await waitFor(() => expect(results).toEqual([false]));
    // Unmounting the host with a confirm still open settles the
    // stored promise rather than leaking it.
    view.unmount();
    await waitFor(() => expect(results).toEqual([false, false]));
  });

  it('resolves true on confirm, false on cancel', async () => {
    render(<ConfirmHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    expect(
      await screen.findByText('Delete filter?'),
    ).toBeInTheDocument();
    expect(
      screen.getByText('This cannot be undone.'),
    ).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: 'Delete' }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('result'))
        .toHaveTextContent('true'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Cancel' }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('result'))
        .toHaveTextContent('false'),
    );
  });
});

describe('usePrompt', () => {
  it('settles pending promises on replace and unmount', async () => {
    const results: (string | null)[] = [];
    function Host() {
      const { prompt, promptElement } = usePrompt();
      return (
        <div>
          <button
            type="button"
            onClick={() => {
              void prompt({ title: 'Name?' }).then((value) =>
                results.push(value),
              );
            }}
          >
            Ask
          </button>
          {promptElement}
        </div>
      );
    }
    const view = render(<Host />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await screen.findByText('Name?');
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    await waitFor(() => expect(results).toEqual([null]));
    view.unmount();
    await waitFor(() => expect(results).toEqual([null, null]));
  });

  it('resolves the typed value on save, null on cancel', async () => {
    render(<PromptHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));

    const input = await screen.findByLabelText('Name');
    // Seeded with the default value.
    expect(input).toHaveValue('My filter');
    fireEvent.change(input, { target: { value: 'Renamed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(screen.getByTestId('result'))
        .toHaveTextContent('Renamed'),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
    fireEvent.click(
      await screen.findByRole('button', { name: 'Cancel' }),
    );
    await waitFor(() =>
      expect(screen.getByTestId('result'))
        .toHaveTextContent('null'),
    );
  });
});
