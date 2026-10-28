import { Component, ErrorInfo, ReactNode } from 'react';
import * as Sentry from '@sentry/react';
import { reportError } from '../errorReporter';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  copied: boolean;
}

/** Markdown error report for pasting into a GitHub issue. */
function buildErrorDetails(error: Error, context?: string): string {
  const header = context
    ? `**Error (${context}):** ${error.name}: ${error.message}`
    : `**Error:** ${error.name}: ${error.message}`;
  return [
    header,
    `**URL:** ${window.location.href}`,
    `**Time:** ${new Date().toISOString()}`,
    `**User agent:** ${navigator.userAgent}`,
    '',
    '```',
    error.stack || 'No stack trace available',
    '```',
  ].join('\n');
}

/**
 * Catches render errors anywhere below it, reports them (toast +
 * Sentry), and shows a Bootstrap-styled fallback with a
 * copy-details button for bug reports. Mounted around <App/> in
 * every main.tsx entry.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null, copied: false };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, copied: false };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    // Sent before reportError's own captureException so the event
    // that survives Sentry's dedupe carries the React component
    // stack — and the `context` tag, which the deduped second
    // capture would otherwise lose. No-op when Sentry is not
    // initialized.
    Sentry.captureException(error, {
      tags: { context: 'React render error' },
      extra: { componentStack: errorInfo.componentStack },
    });
    reportError(error, 'React render error');
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          className="d-flex flex-column align-items-center
            justify-content-center text-center p-4"
          style={{ minHeight: '60vh' }}
        >
          <i
            className="bi bi-exclamation-triangle text-danger
              display-4 mb-3"
          />
          <h2>Something went wrong</h2>
          <p className="text-muted">
            {this.state.error?.message ||
              'An unexpected error occurred. Please try again.'}
          </p>
          <div className="d-flex gap-2">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.href = '/';
              }}
            >
              Go to Home
            </button>
            <button
              type="button"
              className="btn btn-outline-secondary"
              onClick={() => {
                if (!this.state.error) return;
                navigator.clipboard
                  .writeText(
                    buildErrorDetails(
                      this.state.error,
                      'React render error'
                    )
                  )
                  .then(
                    () => this.setState({ copied: true }),
                    () => this.setState({ copied: false })
                  );
              }}
            >
              {this.state.copied ? 'Copied!' : 'Copy error details'}
            </button>
          </div>
          <p className="text-muted small mt-3">
            Please report this bug by pasting the details into a
            GitHub issue.
          </p>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
