#!/usr/bin/env python3
"""Run the full InfoRSS pipeline for one date or date range."""

from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def default_date_range() -> str:
    yesterday = dt.datetime.now().astimezone().date() - dt.timedelta(days=1)
    return yesterday.strftime("%Y%m%d")


def validate_date(value: str) -> None:
    if len(value) != 8 or not value.isdigit():
        raise ValueError(f"expected YYYYMMDD, got {value!r}")
    dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))


def normalize_date_range(value: str | None) -> str:
    raw = (value or default_date_range()).strip()
    if "-" in raw:
        start, end = raw.split("-", 1)
        validate_date(start)
        validate_date(end)
        if start > end:
            raise ValueError("start date is later than end date")
        return f"{start}-{end}"
    validate_date(raw)
    return raw


def run_step(name: str, command: list[str], *, skip: bool = False) -> int:
    if skip:
        print(f"==> Skip: {name}")
        return 0

    print(f"==> {name}")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"Step failed: {name}", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fetch, export, AI processing, and search-index generation.")
    parser.add_argument("date_range", nargs="?", help="Date or date range, e.g. 20260713 or 20260712-20260713.")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip RSS fetching.")
    parser.add_argument("--skip-raw-md", action="store_true", help="Skip raw Markdown export.")
    parser.add_argument("--skip-public-raw", action="store_true", help="Skip public captured raw pages.")
    parser.add_argument("--skip-ai", action="store_true", help="Skip AI brief generation.")
    parser.add_argument("--skip-json", action="store_true", help="Skip structured JSON sidecar export.")
    parser.add_argument("--skip-index", action="store_true", help="Skip search index generation.")
    parser.add_argument("--skip-check", action="store_true", help="Skip generated site consistency checks.")
    args = parser.parse_args()

    try:
        date_range = normalize_date_range(args.date_range)
    except ValueError as exc:
        print(f"Invalid date range: {exc}", file=sys.stderr)
        return 2

    python = sys.executable
    steps = [
        (
            "Fetch RSS",
            [python, "scripts/fetch_rss.py", date_range],
            args.skip_fetch,
        ),
        (
            "Export raw Markdown",
            [python, "scripts/export_md.py", date_range],
            args.skip_raw_md,
        ),
        (
            "Export public captured raw pages",
            [python, "scripts/export_public_raw.py", date_range],
            args.skip_public_raw,
        ),
        (
            "Generate AI brief",
            [python, "scripts/process_ai.py", date_range],
            args.skip_ai,
        ),
        (
            "Export structured JSON",
            [python, "scripts/export_brief_json.py", date_range],
            args.skip_json,
        ),
        (
            "Build search index",
            [python, "scripts/build_search_index.py"],
            args.skip_index,
        ),
        (
            "Check generated site",
            [python, "scripts/check_site.py"],
            args.skip_check,
        ),
    ]

    print(f"Date range: {date_range}")
    for name, command, skip in steps:
        code = run_step(name, command, skip=skip)
        if code != 0:
            return code

    print("Done.")
    print(f"Raw Markdown: content/daily/{date_range}.md")
    print(f"Public raw day page: content/raw/daily/{date_range}.md")
    print(f"AI brief: content/briefs/{date_range}.md")
    print(f"Structured JSON: content/briefs/{date_range}.json")
    print("Search index: assets/search-index.json")
    print("Raw search index: assets/raw-search-index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
