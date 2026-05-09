// A.6 smoke tests for the centralized api client.
// A.9 will expand the frontend test harness; for now this verifies the
// apiFetch contract end-to-end against a stubbed fetch.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { apiFetch, newRequestId, ApiError, REQUEST_ID_HEADER } from './api.js';

const UUIDV7_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('newRequestId', () => {
  it('returns a UUIDv7-formatted string', () => {
    const id = newRequestId();
    expect(id).toMatch(UUIDV7_RE);
  });

  it('returns 1000 unique IDs without collision', () => {
    const ids = new Set();
    for (let i = 0; i < 1000; i++) ids.add(newRequestId());
    expect(ids.size).toBe(1000);
  });

  it('embeds the current time in the leading 48 bits (rough monotonicity)', () => {
    const a = newRequestId();
    const b = newRequestId();
    // First 48 bits encoded as 12 hex chars (with one '-' between byte 4 and 5).
    const aTs = a.replace(/-/g, '').slice(0, 12);
    const bTs = b.replace(/-/g, '').slice(0, 12);
    expect(bTs >= aTs).toBe(true);
  });
});

describe('apiFetch', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends a UUIDv7 X-Request-ID by default', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await apiFetch('/health');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers[REQUEST_ID_HEADER]).toMatch(UUIDV7_RE);
  });

  it('honors a caller-supplied X-Request-ID', async () => {
    fetchMock.mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    const explicit = '11111111-1111-7111-8111-111111111111';
    await apiFetch('/health', { headers: { [REQUEST_ID_HEADER]: explicit } });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers[REQUEST_ID_HEADER]).toBe(explicit);
  });

  it('returns parsed JSON body on 2xx', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ score: 60 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const body = await apiFetch('/v1/analyses-legacy', {
      method: 'POST',
      body: JSON.stringify({ business_name: 'X', location: 'Y' }),
    });
    expect(body).toEqual({ score: 60 });
  });

  it('throws ApiError on non-2xx with backend envelope unwrapped', async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: 'validation_error',
            message: 'Bad input',
            request_id: '22222222-2222-7222-8222-222222222222',
          },
        }),
        { status: 422, headers: { 'Content-Type': 'application/json' } },
      ),
    );

    await expect(apiFetch('/x')).rejects.toMatchObject({
      name: 'ApiError',
      status: 422,
      code: 'validation_error',
      requestId: '22222222-2222-7222-8222-222222222222',
      message: 'Bad input',
    });
  });

  it('falls back to status code when no envelope is present', async () => {
    fetchMock.mockResolvedValue(
      new Response('not json at all', { status: 500 }),
    );

    await expect(apiFetch('/x')).rejects.toMatchObject({
      name: 'ApiError',
      status: 500,
      message: 'Request failed (500)',
    });
  });

  it('Content-Type defaults to application/json', async () => {
    fetchMock.mockResolvedValue(
      new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    await apiFetch('/x');
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['Content-Type']).toBe('application/json');
  });
});
