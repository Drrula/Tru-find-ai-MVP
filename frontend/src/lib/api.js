// Centralized HTTP access to the backend API.
//
// Per A.6 + the strategic platform direction in project memory:
//   - Single fetch surface. Components must not call fetch() directly.
//   - Env-driven base URL via VITE_API_BASE_URL (empty in dev — Vite proxy
//     forwards to localhost:8000).
//   - Mints and sends X-Request-ID (UUIDv7, format matches backend
//     app/core/ids.py per ADR-033) so request correlation flows
//     browser → backend → event publisher → log line in one chain.
//   - Backend error envelope unwrapped into a typed ApiError carrying
//     status / code / requestId / body for callers to inspect.
//   - No DOM or React coupling: reusable from a future React Native
//     client or CLI without changes.

const REQUEST_ID_HEADER = 'X-Request-ID';
const _viteEnv = (typeof import.meta !== 'undefined' && import.meta.env) || {};
const BASE_URL = _viteEnv.VITE_API_BASE_URL ?? '';

/**
 * Generate a UUIDv7 (RFC 9562). Mirrors backend/app/core/ids.py — same
 * format on both sides of the wire so request_id round-trips cleanly.
 */
function newRequestId() {
  const ts = BigInt(Date.now());
  const rand = new Uint8Array(10);
  crypto.getRandomValues(rand);

  const b = new Uint8Array(16);
  // 48-bit big-endian timestamp
  b[0] = Number((ts >> 40n) & 0xffn);
  b[1] = Number((ts >> 32n) & 0xffn);
  b[2] = Number((ts >> 24n) & 0xffn);
  b[3] = Number((ts >> 16n) & 0xffn);
  b[4] = Number((ts >> 8n) & 0xffn);
  b[5] = Number(ts & 0xffn);
  // version 7 in upper nibble of byte 6, 4 random bits
  b[6] = 0x70 | (rand[0] & 0x0f);
  b[7] = rand[1];
  // variant 10 in upper 2 bits of byte 8, 6 random bits
  b[8] = 0x80 | (rand[2] & 0x3f);
  // remaining 7 bytes random
  for (let i = 0; i < 7; i++) b[9 + i] = rand[3 + i];

  const hex = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-');
}

/**
 * Typed error matching the backend's stable envelope:
 *   { error: { code, message, request_id } }
 * Plus the raw body and HTTP status for callers that need them.
 */
class ApiError extends Error {
  constructor(message, { status, code, requestId, body }) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.body = body;
  }
}

/**
 * Centralized fetch. Components must use this, not fetch() directly.
 *
 * @param {string} path  Path relative to VITE_API_BASE_URL (or absolute origin).
 * @param {RequestInit} init  Standard fetch options. Body should be a string.
 * @returns {Promise<unknown>}  Parsed JSON body (or null on empty response).
 * @throws {ApiError} on non-2xx response.
 */
async function apiFetch(path, init = {}) {
  const url = `${BASE_URL}${path}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(init.headers ?? {}),
  };
  if (!headers[REQUEST_ID_HEADER]) {
    headers[REQUEST_ID_HEADER] = newRequestId();
  }
  const requestId = headers[REQUEST_ID_HEADER];

  const response = await fetch(url, { ...init, headers });

  let body = null;
  try {
    body = await response.json();
  } catch {
    // Empty or non-JSON body; leave body=null.
  }

  if (!response.ok) {
    const envelope = body?.error ?? {};
    throw new ApiError(envelope.message ?? `Request failed (${response.status})`, {
      status: response.status,
      code: envelope.code,
      requestId:
        envelope.request_id ??
        response.headers.get(REQUEST_ID_HEADER) ??
        requestId,
      body,
    });
  }

  return body;
}

export { apiFetch, newRequestId, ApiError, REQUEST_ID_HEADER, BASE_URL };
