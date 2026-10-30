import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import {
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import Register from './Register';
import { register } from '../api';
import { navigate } from '../next';
import { ApiError } from '../../shared/api/errors';
import type { AuthOut } from '../api';

vi.mock('../api', () => ({
  register: vi.fn(),
}));

// Keep the real safeNext; observe the navigation seam.
vi.mock('../next', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../next')>();
  return { ...mod, navigate: vi.fn() };
});

const mockedRegister = vi.mocked(register);
const mockedNavigate = vi.mocked(navigate);

const AUTH_OUT: AuthOut = {
  user: { id: 1, username: 'alice', email: '', is_staff: false },
};

function renderRegister(entry = '/register') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Register />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/Username/), {
    target: { value: 'alice' },
  });
  fireEvent.change(screen.getByLabelText(/^Password/), {
    target: { value: 'S3cure!pass' },
  });
  fireEvent.change(screen.getByLabelText(/Confirm password/), {
    target: { value: 'S3cure!pass' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: /register/i }),
  );
}

describe('Register', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('posts the form and navigates to the sanitized ?next=',
    async () => {
      mockedRegister.mockResolvedValue(AUTH_OUT);
      renderRegister('/register?next=/vacancies/');
      fillAndSubmit();
      await waitFor(() =>
        expect(mockedNavigate).toHaveBeenCalledWith('/vacancies/'),
      );
      expect(mockedRegister).toHaveBeenCalledWith({
        username: 'alice',
        email: '',
        password: 'S3cure!pass',
        password_confirm: 'S3cure!pass',
      });
    });

  it('surfaces the API detail on validation failure', async () => {
    mockedRegister.mockRejectedValue(
      new ApiError('Request failed: 400', 400, 'Bad Request', {
        error: 'bad_request',
        detail: 'A user with this username already exists.',
        code: 'username_taken',
      }),
    );
    renderRegister();
    fillAndSubmit();
    expect(
      await screen.findByText(
        'A user with this username already exists.',
      ),
    ).toBeInTheDocument();
    expect(mockedNavigate).not.toHaveBeenCalled();
  });
});
