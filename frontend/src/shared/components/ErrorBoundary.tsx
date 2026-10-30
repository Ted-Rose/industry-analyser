import { Component, ErrorInfo, ReactNode } from 'react';
import * as Sentry from '@sentry/react';
import { AlertTriangle } from 'lucide-react';
import { reportError } from '../errorReporter';
import '../styles/ia-components.css';

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
 * Sentry), and shows a design-system fallback — the ErrorState +
 * Button pairing from plan §6, rendered with `ia-` classes from
 * styles/ia-components.css (imported above so vite co-bundles the
 * rules into every entry) so it holds up while Bootstrap is
 * still loaded on legacy entries (plan §4.4). Mounted around
 * <App/> in every main.tsx entry.
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
        <div className="ia-fallback" role="alert">
          <span className="ia-fallback__icon" aria-hidden="true">
            <AlertTriangle size={40} />
          </span>
          <h2 className="ia-fallback__title">
            Something went wrong
          </h2>
          <p className="ia-fallback__message">
            {this.state.error?.message ||
              'An unexpected error occurred. Please try again.'}
          </p>
          <div className="ia-fallback__actions">
            <button
              type="button"
              className="ia-btn ia-btn--primary"
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.href = '/';
              }}
            >
              Go to Home
            </button>
            <button
              type="button"
              className="ia-btn ia-btn--secondary"
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
          <p className="ia-fallback__hint">
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
