import { describe, expect, it } from 'vitest';
import type { ErrorEvent, EventHint } from '@sentry/react';
import { initSentry, sentryBeforeSend } from './sentry';

const event = { event_id: 'test-event' } as ErrorEvent;
const hintOf = (err: unknown): EventHint => ({
  originalException: err,
});

function exceptionEvent(
  value: string,
  type = 'Error',
  mechanismType?: string
): ErrorEvent {
  return {
    event_id: 'test-event',
    exception: {
      values: [
        {
          type,
          value,
          mechanism: mechanismType
            ? { type: mechanismType }
            : undefined,
        },
      ],
    },
  } as ErrorEvent;
}

describe('sentryBeforeSend', () => {
  it('passes unexpected errors through', () => {
    const result = sentryBeforeSend(event, hintOf(new Error('boom')));
    expect(result).toBe(event);
  });

  it('passes non-Error rejections through', () => {
    expect(sentryBeforeSend(event, hintOf('plain failure')))
      .toBe(event);
  });

  it('drops AbortError (routine fetch cancellation)', () => {
    const err = new Error('aborted');
    err.name = 'AbortError';
    expect(sentryBeforeSend(event, hintOf(err))).toBeNull();
  });

  it('drops DOMException AbortError (real fetch aborts)', () => {
    // fetch aborts reject with a DOMException, not an Error.
    const err = new DOMException('aborted', 'AbortError');
    expect(sentryBeforeSend(event, hintOf(err))).toBeNull();
  });

  it('drops ChunkLoadError via the exception value', () => {
    const ev = exceptionEvent(
      'Loading chunk 42 failed.',
      'ChunkLoadError'
    );
    expect(sentryBeforeSend(ev, hintOf(new Error('x'))))
      .toBeNull();
  });

  it('drops ChunkLoadError via the exception type alone', () => {
    // A ChunkLoadError whose message wording is unusual must still
    // be dropped — the type string rides the match haystack.
    const ev = exceptionEvent('asset blew up', 'ChunkLoadError');
    expect(sentryBeforeSend(ev, hintOf(new Error('x'))))
      .toBeNull();
  });

  it('drops message-only stale-chunk onerror events', () => {
    // Stale tabs after a deploy hit window.onerror with no
    // exception object — only event.message carries the text.
    const ev = {
      event_id: 'e',
      message: 'Loading CSS chunk styles failed.',
    } as ErrorEvent;
    expect(sentryBeforeSend(ev, hintOf('raw string'))).toBeNull();
  });

  it('drops "Loading chunk N failed" message-only events', () => {
    const ev = {
      event_id: 'e',
      message: 'Loading chunk 7 failed',
    } as ErrorEvent;
    expect(sentryBeforeSend(ev, hintOf('raw'))).toBeNull();
  });

  it('drops ResizeObserver loop noise', () => {
    const ev = {
      event_id: 'e',
      message:
        'ResizeObserver loop completed with undelivered ' +
        'notifications.',
    } as ErrorEvent;
    expect(sentryBeforeSend(ev, hintOf('raw'))).toBeNull();
    const ev2 = exceptionEvent(
      'ResizeObserver loop limit exceeded'
    );
    expect(sentryBeforeSend(ev2, hintOf(new Error('x'))))
      .toBeNull();
  });

  it('tags TypeError network failures, does not drop them', () => {
    const err = new TypeError('Failed to fetch');
    const ev = exceptionEvent('Failed to fetch', 'TypeError');
    const result = sentryBeforeSend(ev, hintOf(err));
    expect(result).toBe(ev);
    expect(result?.tags?.errorKind).toBe('network');
  });

  it('keeps non-network TypeErrors untagged', () => {
    const err = new TypeError('undefined is not a function');
    const ev = exceptionEvent(
      'undefined is not a function',
      'TypeError'
    );
    const result = sentryBeforeSend(ev, hintOf(err));
    expect(result).toBe(ev);
    expect(result?.tags?.errorKind).toBeUndefined();
  });

  it('tags GlobalHandlers-captured rejections with context', () => {
    // GlobalHandlers captures first and wins dedupe, so the
    // surviving event lacks the context tag the app's own
    // captureException carried.
    const rejectionEvent = exceptionEvent(
      'async failed',
      'Error',
      'onunhandledrejection'
    );

    const result = sentryBeforeSend(
      rejectionEvent,
      hintOf(new Error('async failed'))
    );

    expect(result?.tags?.context).toBe(
      'Unhandled promise rejection'
    );
  });

  it('keeps an existing context tag on rejection events', () => {
    const taggedEvent: ErrorEvent = {
      ...exceptionEvent('x', 'Error', 'onunhandledrejection'),
      tags: { context: 'Custom context' },
    };

    const result = sentryBeforeSend(
      taggedEvent,
      hintOf(new Error('async failed'))
    );

    expect(result?.tags?.context).toBe('Custom context');
  });
});

describe('initSentry', () => {
  it('is a no-op without a DSN (no spa-bootstrap)', () => {
    // jsdom has no #spa-bootstrap node and no VITE_SENTRY_DSN —
    // init must silently return.
    expect(() => initSentry()).not.toThrow();
  });
});
