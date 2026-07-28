#!/usr/bin/env python3
"""Publish a Markdown newsletter to the configured Notion data source.

Required environment variables:
- NOTION_TOKEN
- NOTION_DATA_SOURCE_ID

This script creates the database page and stores the Markdown as paragraph blocks.
For production use, extend markdown_to_blocks for richer tables, code, and diagrams.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from notion_client import Client


def markdown_to_blocks(markdown: str) -> list[dict]:
    blocks: list[dict] = []
    for paragraph in (part.strip() for part in markdown.split("\n\n")):
        if not paragraph:
            continue
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": paragraph[:2000]}}]},
            }
        )
    return blocks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown_file", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--topic", default="Agents")
    parser.add_argument("--link", required=True)
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    data_source_id = os.environ.get("NOTION_DATA_SOURCE_ID")
    if not token or not data_source_id:
        raise SystemExit("NOTION_TOKEN and NOTION_DATA_SOURCE_ID are required")

    client = Client(auth=token)
    content = args.markdown_file.read_text(encoding="utf-8")
    page = client.pages.create(
        parent={"database_id": data_source_id},
        properties={
            "Note": {"title": [{"text": {"content": args.title}}]},
            "Status": {"select": {"name": "Draft"}},
            "Summary": {"rich_text": [{"text": {"content": args.summary}}]},
            "Topic": {"select": {"name": args.topic}},
            "Link": {"url": args.link},
        },
        children=markdown_to_blocks(content),
    )
    print(page["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
