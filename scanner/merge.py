"""Merge chunk JSON files produced by parallel scan into single results.json."""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="docs/data/results.json")
    p.add_argument("--chunk-dir", default="docs/data")
    args = p.parse_args()

    chunk_files = sorted(glob.glob(os.path.join(args.chunk_dir, "**", "chunk_*.json"), recursive=True))
    if not chunk_files:
        chunk_files = sorted(glob.glob(os.path.join(args.chunk_dir, "chunk_*.json")))

    if not chunk_files:
        print("No chunk files found.")
        return

    all_results   = []
    total_scanned = 0
    generated_at  = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    market_env    = None

    for cf in chunk_files:
        with open(cf, encoding="utf-8") as f:
            data = json.load(f)
        all_results.extend(data.get("results", []))
        total_scanned += data.get("total_scanned", 0)
        if data.get("generated_at"):
            generated_at = data["generated_at"]
        if market_env is None and data.get("market_env"):
            market_env = data["market_env"]

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    output = {
        "generated_at":  generated_at,
        "total_scanned": total_scanned,
        "total_signals": len(all_results),
        "market_env":    market_env,
        "results":       all_results,
    }

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=None)

    print(f"Merged {len(chunk_files)} chunks → {len(all_results)} signals → {args.output}")


if __name__ == "__main__":
    main()
