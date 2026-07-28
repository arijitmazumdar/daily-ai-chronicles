#!/usr/bin/env python3
"""Create a dated Markdown newsletter skeleton."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def slugify(value: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("title")
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    run_date = date.fromisoformat(args.date)
    slug = slugify(args.title)
    path = ROOT / "newsletters" / f"{run_date:%Y}" / f"{run_date:%m}" / f"{run_date.isoformat()}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")

    path.write_text(
        f"# {args.title}\n\n"
        f"**Date:** {run_date.isoformat()}  \n"
        "**Topic:** Agents  \n"
        "**Primary source:** <add URL>\n\n"
        "## Executive summary\n\n"
        "## Core model\n\n"
        "## Architecture\n\n"
        "## Implementation\n\n"
        "## Failure modes\n\n"
        "## Reading\n",
        encoding="utf-8",
    )
    print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
