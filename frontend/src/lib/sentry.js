// Sentry browser init.
//
// Per ADR-030 + A.12. Initializes when VITE_SENTRY_DSN is set; otherwise
// no-op so callers (main.jsx, error handlers) don't need conditional checks.
// Conservative defaults: 10% trace sampling, send_default_pii off.
//
// PII redaction: Sentry's send_default_pii=false prevents the SDK from
// auto-collecting headers / cookies. App-level scrubbing of payloads
// happens before they reach Sentry.

import * as Sentry from "@sentry/react";

const _viteEnv = (typeof import.meta !== "undefined" && import.meta.env) || {};
const DSN = _viteEnv.VITE_SENTRY_DSN ?? "";
const ENV = _viteEnv.VITE_APP_ENV ?? _viteEnv.MODE ?? "development";

let _initialized = false;

/**
 * Initialize Sentry. Idempotent — safe to call multiple times.
 * No-op when VITE_SENTRY_DSN is empty.
 */
export function initSentry() {
  if (!DSN || _initialized) return;

  Sentry.init({
    dsn: DSN,
    environment: ENV,
    tracesSampleRate: 0.1,
    sendDefaultPii: false,
  });

  _initialized = true;
}

/**
 * Capture an exception explicitly. No-op when Sentry isn't initialized.
 * Useful for caught errors that Sentry's default unhandled-error capture
 * wouldn't see (e.g. caught in a try/catch and surfaced to the user).
 */
export function reportException(error, context = {}) {
  if (!_initialized) return;
  Sentry.captureException(error, { contexts: { app: context } });
}

// Test-only: reset internal state. Used by sentry.test.js to isolate tests.
export function _resetForTests() {
  _initialized = false;
}
