import { describe, expect, it } from 'vitest';
import { ApiError, errorDetail } from './errors';

describe('errorDetail', () => {
  it('prefers the server detail field', () => {
    const err = new ApiError('Request failed: 400', 400, '', {
      error: 'bad_request',
      detail: 'Name is required',
    });
    expect(errorDetail(err)).toBe('Name is required');
  });

  it('falls back to the Error message without a body detail', () => {
    const err = new ApiError('Request failed: 500', 500, 'ISE', {
      error: 'server_error',
    });
    expect(errorDetail(err)).toBe('Request failed: 500');
  });

  it('handles non-ApiError failures', () => {
    expect(errorDetail(new Error('boom'))).toMatch(/Network error/);
  });
});
