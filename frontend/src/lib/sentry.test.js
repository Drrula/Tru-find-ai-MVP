// A.12 smoke tests for the Sentry browser wire-up.
// Mocks @sentry/react so tests don't need a real DSN.

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock @sentry/react before the SUT loads.
vi.mock("@sentry/react", () => ({
  init: vi.fn(),
  captureException: vi.fn(),
}));

import * as Sentry from "@sentry/react";
import { initSentry, reportException, _resetForTests } from "./sentry.js";

beforeEach(() => {
  vi.clearAllMocks();
  _resetForTests();
});

describe("initSentry", () => {
  it("is a no-op when VITE_SENTRY_DSN is unset", () => {
    // import.meta.env.VITE_SENTRY_DSN is undefined in test env; exercises the gate.
    initSentry();
    expect(Sentry.init).not.toHaveBeenCalled();
  });

  // Note: testing the with-DSN branch requires patching import.meta.env at
  // module-load time, which is awkward in vitest. The no-op-when-unset gate
  // is the operational concern (correct DSN behavior verified manually
  // against a real Sentry project per the README test plan).
});

describe("reportException", () => {
  it("is a no-op when Sentry isn't initialized", () => {
    reportException(new Error("boom"));
    expect(Sentry.captureException).not.toHaveBeenCalled();
  });
});
