#!/usr/bin/env python3
"""Standalone notification script — run after merge.py."""

from __future__ import annotations

import argparse
import glob
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from discord_notify import send_discord_notification
from market_filter import check_market_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

SCORE_DROP_THRESHOLD = 10


def find_yesterday_results(data_dir: str) -> dict | None:
    pattern = os.path.join(data_dir, "results_????-??-??.json")
    archives = sorted(glob.glob(pattern))
    if not archives:
        return None
    with open(archives[-1], encoding="utf-8") as f:
        return json.load(f)


def check_score_drops(
    today_data: dict,
    yesterday_data: dict,
    threshold: int = SCORE_DROP_THRESHOLD,
) -> list[dict]:
    today_map     = {r["code"]: r for r in today_data.get("results", [])}
    yesterday_map = {r["code"]: r for r in yesterday_data.get("results", [])}

    drops = []
    for code, yest in yesterday_map.items():
        score_yest = yest.get("score", 0)
        if score_yest < 40:
            continue

        if code not in today_map:
            drops.append({
                "code": code,
                "name": yest.get("name", code),
                "score_yesterday": score_yest,
                "score_today": None,
                "drop": score_yest,
                "disappeared": True,
            })
        else:
            score_today = today_map[code].get("score", 0)
            drop = score_yest - score_today
            if drop >= threshold:
                drops.append({
                    "code": code,
                    "name": today_map[code].get("name", code),
                    "score_yesterday": score_yest,
                    "score_today": score_today,
                    "drop": drop,
                    "disappeared": False,
                })

    drops.sort(key=lambda x: x["drop"], reverse=True)
    return drops[:10]


def send_score_drop_notification(drops: list[dict], generated_at: str) -> None:
    import requests

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    if not drops:
        logger.info("No score drops to notify")
        return

    fields = []
    for d in drops:
        if d["disappeared"]:
            value = f"Score **{d['score_yesterday']}** → **Dropped out of scan**"
        else:
            value = f"Score **{d['score_yesterday']}** → **{d['score_today']}** (▼{d['drop']})"
        fields.append({
            "name": f"**{d['code']} {d['name']}**",
            "value": value,
            "inline": False,
        })

    payload = {
        "embeds": [{
            "title": "⚠️ Score Drop Alert",
            "description": (
                f"Stocks with a score drop of {SCORE_DROP_THRESHOLD}+ points vs yesterday.\n"
                f"If holding, consider reviewing your position.\nUpdated: {generated_at}"
            ),
            "color": 0xf0a500,
            "fields": fields,
            "footer": {"text": "Not investment advice"},
        }]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.ok:
            logger.info("Score drop notification sent (%d stocks)", len(drops))
        else:
            logger.warning("Score drop notification failed: %s %s", res.status_code, res.text[:200])
    except Exception as e:
        logger.warning("Score drop notification error: %s", e)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="docs/data/results.json")
    args = p.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    market_env = data.get("market_env") or check_market_env()

    send_discord_notification(
        results=data.get("results", []),
        market_env=market_env,
        generated_at=data.get("generated_at", ""),
    )

    data_dir = os.path.dirname(args.input)
    yesterday_data = find_yesterday_results(data_dir)
    if yesterday_data:
        drops = check_score_drops(data, yesterday_data)
        send_score_drop_notification(drops, data.get("generated_at", ""))
    else:
        logger.info("No archive found for score drop comparison")


if __name__ == "__main__":
    main()
