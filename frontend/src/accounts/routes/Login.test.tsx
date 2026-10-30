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
import Login from './Login';
import { login } from '../api';
import { navigate } from '../next';
import { ApiError } from '../../shared/api/errors';
import type { AuthOut } from '../api';

vi.mock('../api', () => ({
  login: vi.fn(),
}));

// Keep the real safeNext; observe the navigation seam.
vi.mock('../next', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../next')>();
  return { ...mod, navigate: vi.fn() };
});

const mockedLogin = vi.mocked(login);
const mockedNavigate = vi.mocked(navigate);

const AUTH_OUT: AuthOut = {
  user: { id: 1, username: 'alice', email: '', is_staff: false },
};

function renderLogin(entry = '/login') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <Login />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText(/Username/), {
    target: { value: 'alice' },
  });
  fireEvent.change(screen.getByLabelText(/Password/), {
    target: { value: 'S3cure!pass' },
  });
  fireEvent.click(
    screen.getByRole('button', { name: /sign in/i }),
  );
}

describe('Login', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('navigates to the sanitized ?next= on success', async () => {
    mockedLogin.mockResolvedValue(AUTH_OUT);
    renderLogin('/login?next=/dashboard/');
    fillAndSubmit();
    await waitFor(() =>
      expect(mockedNavigate).toHaveBeenCalledWith('/dashboard/'),
    );
    expect(mockedLogin).toHaveBeenCalledWith({
      username: 'alice',
      password: 'S3cure!pass',
    });
  });

  it('falls back to / when ?next= is not same-origin', async () => {
    mockedLogin.mockResolvedValue(AUTH_OUT);
    renderLogin('/login?next=https%3A%2F%2Fevil.example%2F');
    fillAndSubmit();
    await waitFor(() =>
      expect(mockedNavigate).toHaveBeenCalledWith('/'),
    );
  });

  it('surfaces the API detail on credential failure', async () => {
    mockedLogin.mockRejectedValue(
      new ApiError('Request failed: 401', 401, 'Unauthorized', {
        error: 'unauthenticated',
        detail: 'Invalid username or password.',
        code: 'invalid_credentials',
      }),
    );
    renderLogin();
    fillAndSubmit();
    expect(
      await screen.findByText('Invalid username or password.'),
    ).toBeInTheDocument();
    expect(mockedNavigate).not.toHaveBeenCalled();
  });
});
