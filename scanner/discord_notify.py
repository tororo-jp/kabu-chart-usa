"""Discord webhook notification for recommended signals — US stocks."""

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

SCORE_MIN = 60
PROB_MIN  = 0.60
RR_MIN    = 2.0
MAX_PICKS = 5


def send_discord_notification(
    results: list[dict],
    market_env: dict,
    generated_at: str,
) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.info("DISCORD_WEBHOOK_URL not set, skipping notification")
        return

    picks = [
        r for r in results
        if r.get("score", 0)       >= SCORE_MIN
        and r.get("probability", 0) >= PROB_MIN
        and r.get("rr_ratio", 0)    >= RR_MIN
        and not r.get("earnings_warning", False)
    ][:MAX_PICKS]

    bull  = market_env.get("bull")
    sp500 = market_env.get("sp500") or 0
    sma200 = market_env.get("sma200") or 0

    if bull is True:
        mkt_line = f"\U0001f7e2 **Bull Market** S&P 500 {sp500:,.2f} > 200MA {sma200:,.2f}"
        color = 0x3fb950
    elif bull is False:
        mkt_line = f"\U0001f534 **Bear Market** S&P 500 {sp500:,.2f} < 200MA {sma200:,.2f} — Enter cautiously"
        color = 0xf85149
    else:
        mkt_line = "⚪ Market data unavailable"
        color = 0x7d8590

    fields = []
    for r in picks:
        patterns = ", ".join(p["label"] for p in r.get("patterns", [])[:2])
        fields.append({
            "name": f"**{r['code']} {r.get('name', r['code'])}**",
            "value": (
                f"Score **{r['score']}** | Prob **{round(r['probability'] * 100)}%** | "
                f"RR **{r.get('rr_ratio', 0):.1f}:1**\n"
                f"Entry: **${r.get('price', 0):,.2f}** | "
                f"Target: ${r.get('target', 0):,.2f} | "
                f"Stop: ${r.get('stop_loss', 0):,.2f}\n"
                f"Patterns: {patterns or '—'}"
            ),
            "inline": False,
        })

    if not fields:
        fields.append({
            "name": "No signals today",
            "value": (
                f"No stocks met all criteria: "
                f"Score {SCORE_MIN}+, Prob {round(PROB_MIN * 100)}%+, "
                f"RR {RR_MIN}+, no earnings."
            ),
            "inline": False,
        })

    payload = {
        "embeds": [{
            "title": "\U0001f4ca US Stock Technical Scanner — Today's Picks",
            "description": f"{mkt_line}\nUpdated: {generated_at}",
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Criteria: Score {SCORE_MIN}+ | Prob {round(PROB_MIN*100)}%+ | RR {RR_MIN}+ | No earnings | Not investment advice"
            },
        }]
    }

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.ok:
            logger.info("Discord notification sent (%d picks)", len(picks))
        else:
            logger.warning("Discord notification failed: %s %s", res.status_code, res.text[:200])
    except Exception as e:
        logger.warning("Discord notification error: %s", e)
