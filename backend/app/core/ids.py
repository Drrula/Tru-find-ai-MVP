"""UUIDv7 generator (RFC 9562).

Time-ordered UUIDs: B-tree-friendly inserts, no leak of "we have N rows"
via integer IDs, cross-shard safe by construction. Application-side
generation lets us mint IDs before insert (useful for idempotency and
outbox patterns). Per ADR-033.
"""

from __future__ import annotations

import os
import time
from uuid import UUID


def new_id() -> UUID:
    """Generate a UUIDv7 (time-ordered, RFC 9562).

    Layout (128 bits):
      - 48 bits: Unix timestamp in milliseconds (big-endian)
      - 4 bits:  version = 7
      - 12 bits: random
      - 2 bits:  variant = 10 (RFC 4122)
      - 62 bits: random
    """
    ts_ms = int(time.time() * 1000)
    rand = os.urandom(10)

    b = bytearray(16)
    # 48-bit big-endian timestamp
    b[0] = (ts_ms >> 40) & 0xFF
    b[1] = (ts_ms >> 32) & 0xFF
    b[2] = (ts_ms >> 24) & 0xFF
    b[3] = (ts_ms >> 16) & 0xFF
    b[4] = (ts_ms >> 8) & 0xFF
    b[5] = ts_ms & 0xFF
    # version 7 in upper nibble of byte 6, plus 4 random bits
    b[6] = 0x70 | (rand[0] & 0x0F)
    b[7] = rand[1]
    # variant 10 in upper 2 bits of byte 8, plus 6 random bits
    b[8] = 0x80 | (rand[2] & 0x3F)
    # remaining 7 bytes random
    b[9:16] = rand[3:10]

    return UUID(bytes=bytes(b))
