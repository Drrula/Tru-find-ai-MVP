"""Batch-score a CSV of businesses against a running TruFindAI backend.

Reads a CSV with at least `business_name` and `location` columns, POSTs
each row to the analyze endpoint, writes the input columns plus `score`,
`gaps`, and `summary` to an output CSV.

Stdlib-only — no third-party dependencies. Suitable for any operator
with Python 3.13+ and access to a running TruFindAI backend. Replaces
the pre-A.8 `run_batch_test.py` (which had hardcoded OneDrive paths and
a hardcoded localhost URL).

Usage:
    python infra/scripts/batch_score.py \\
        --input  path/to/leads.csv \\
        --output path/to/scored.csv \\
        --base-url http://127.0.0.1:8000

See infra/scripts/README.md for full options + examples.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = os.environ.get("BATCH_SCORE_BASE_URL", "http://127.0.0.1:8000")
DEFAULT_ENDPOINT = "/analyze-business"  # legacy alias preserved through Phase B (ADR-005)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Batch-score a CSV of businesses against the TruFindAI API.",
    )
    p.add_argument("--input", "-i", required=True, help="Input CSV path.")
    p.add_argument("--output", "-o", required=True, help="Output CSV path.")
    p.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "Backend base URL "
            f"(default reads BATCH_SCORE_BASE_URL env, fallback {DEFAULT_BASE_URL})."
        ),
    )
    p.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=(
            f"Endpoint path (default {DEFAULT_ENDPOINT}). Phase C will introduce "
            "/v1/analyses async-poll; this script will be updated then."
        ),
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Per-request timeout in seconds (default: 30).",
    )
    return p.parse_args()


def post_json(url: str, payload: dict, timeout: int) -> dict:
    """POST a JSON payload and return the parsed response. Raises on non-2xx."""
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    args = parse_args()
    url = f"{args.base_url}{args.endpoint}"

    with (
        open(args.input, newline="", encoding="utf-8-sig") as infile,
        open(args.output, "w", newline="", encoding="utf-8") as outfile,
    ):
        reader = csv.DictReader(infile)
        if reader.fieldnames is None:
            print("ERROR: input CSV has no header row.", file=sys.stderr)
            return 2

        # Strip BOM / whitespace from header names defensively.
        reader.fieldnames = [
            name.strip().replace("﻿", "") for name in reader.fieldnames
        ]
        if (
            "business_name" not in reader.fieldnames
            or "location" not in reader.fieldnames
        ):
            print(
                f"ERROR: input CSV must include `business_name` and `location` "
                f"columns; got {reader.fieldnames}",
                file=sys.stderr,
            )
            return 2

        out_fields = list(reader.fieldnames) + ["score", "gaps", "summary"]
        writer = csv.DictWriter(outfile, fieldnames=out_fields)
        writer.writeheader()

        ok = 0
        failed = 0
        for row in reader:
            payload = {
                "business_name": row["business_name"],
                "location": row["location"],
            }
            try:
                data = post_json(url, payload, args.timeout)
            except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as exc:
                print(f"FAIL  {row['business_name']!r}: {exc}", file=sys.stderr)
                row["score"] = ""
                row["gaps"] = ""
                row["summary"] = f"ERROR: {exc}"
                writer.writerow(row)
                failed += 1
                continue

            row["score"] = data.get("score", "")
            row["gaps"] = " | ".join(data.get("gaps") or [])
            row["summary"] = data.get("summary", "")
            writer.writerow(row)
            print(f"OK    {row['business_name']!r}: {row['score']}")
            ok += 1

    print(f"\nDONE - {ok} succeeded, {failed} failed. Output: {args.output}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
