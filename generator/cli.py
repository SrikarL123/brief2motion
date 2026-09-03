#!/usr/bin/env python3
"""CLI entry point.

Usage:
    python cli.py "a 12 second ad for a developer tool, dark theme, ..."
    python cli.py --brief-file briefs/ad.txt
    python cli.py "..." --out out --repair-cap 3

Environment:
    HYPERFRAMES_API_KEY   (required) bearer token for the model gateway
    HYPERFRAMES_API_BASE  (default: https://llm.ganeshnayak.in/v1)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from openai import OpenAI

sys.path.insert(0, str(Path(__file__).parent))
from src.pipeline import run  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Brief -> verified MP4 via HyperFrames")
    ap.add_argument("brief", nargs="?", help="Plain-language brief")
    ap.add_argument("--brief-file", type=Path, help="Read the brief from a file instead")
    ap.add_argument("--out", type=Path, default=Path("out"), help="Output root directory")
    ap.add_argument("--cache", type=Path, default=Path(".plan-cache"), help="Plan cache directory")
    ap.add_argument("--repair-cap", type=int, default=3)
    ap.add_argument("--model", default="gpt-5.5")
    args = ap.parse_args()

    if args.brief_file:
        brief = args.brief_file.read_text(encoding="utf-8").strip()
    elif args.brief:
        brief = args.brief.strip()
    else:
        ap.error("provide a brief as an argument or via --brief-file")
        return 2

    api_key = os.environ.get("HYPERFRAMES_API_KEY")
    if not api_key:
        print("HYPERFRAMES_API_KEY is not set.", file=sys.stderr)
        return 2
    base_url = os.environ.get("HYPERFRAMES_API_BASE", "https://llm.ganeshnayak.in/v1")
    client = OpenAI(api_key=api_key, base_url=base_url)

    result = run(
        brief=brief,
        out_root=args.out,
        client=client,
        cache_dir=args.cache,
        repair_cap=args.repair_cap,
        model=args.model,
    )

    print()
    if result.success:
        print(f"SUCCESS after {result.attempts} attempt(s)")
        print(f"  video:        {result.mp4_path}")
        print(f"  check output: {result.project_dir / 'check-output.json'}")
        print(f"  plan:         {result.project_dir / 'plan.json'}")
        if result.fallback_assets:
            print(f"  degraded (no-image fallback) scenes: {result.fallback_assets}")
        return 0
    else:
        print(f"FAILED after {result.attempts} attempt(s): {result.failure_reason}")
        print(f"  see: {result.project_dir / 'failure-report.json'}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
