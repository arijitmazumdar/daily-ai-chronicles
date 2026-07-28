#!/usr/bin/env python3
"""Validate newsletter metadata JSON against the repository schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "newsletter.schema.json"


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/validate.py <metadata.json>", file=sys.stderr)
        return 2

    metadata_path = Path(sys.argv[1])
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    errors = sorted(Draft202012Validator(schema).iter_errors(metadata), key=lambda e: list(e.path))
    if errors:
        for error in errors:
            location = ".".join(str(part) for part in error.path) or "<root>"
            print(f"{location}: {error.message}", file=sys.stderr)
        return 1

    print(f"Valid: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
