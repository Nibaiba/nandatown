# SPDX-License-Identifier: Apache-2.0
"""Compare two marketplace traces on volume and distribution, not just ratios.

``nest report`` gives ratio metrics (``deal_rate``, ``delivery_rate``). This
script adds the two things that turned out to matter for this experiment:
how much market *activity* survived, and *who* it survived for.

Stdlib only. Reads traces produced by ``nest run``.

Example::

    python analyze.py traces/marketplace.jsonl traces/marketplace_drop05.jsonl
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: str | Path) -> list[dict[str, Any]]:
    """Read a JSONL trace into a list of events."""
    with Path(path).open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def body(event: dict[str, Any]) -> str:
    """Strip the signature suffix the reference agents append to every payload."""
    return str(event.get("msg", "")).rsplit("|sig:", 1)[0]


def gini(values: list[int]) -> float:
    """Gini coefficient. 0.0 = perfectly even, 1.0 = one agent takes everything."""
    ordered = sorted(values)
    n = len(ordered)
    total = sum(ordered)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum((i + 1) * v for i, v in enumerate(ordered))
    return (2 * weighted) / (n * total) - (n + 1) / n


def summarize(path: str | Path) -> dict[str, Any]:
    """Compute volume, ratio, and distribution figures for one trace."""
    events = load(path)

    buyers: set[str] = set()
    sellers: set[str] = set()
    deals_by_seller: Counter[str] = Counter()
    deals_by_buyer: Counter[str] = Counter()
    buys = sold = rejects = sends = receives = 0

    for event in events:
        agent = str(event.get("agent", ""))
        if agent.startswith("buyer"):
            buyers.add(agent)
        elif agent.startswith("seller"):
            sellers.add(agent)

        kind = event.get("kind")
        if kind == "receive":
            receives += 1
            continue
        if kind != "send":
            continue
        sends += 1

        payload = body(event)
        if payload.startswith("buy:"):
            buys += 1
        elif payload.startswith("sold:"):
            sold += 1
            deals_by_seller[agent] += 1
            deals_by_buyer[str(event.get("to", ""))] += 1
        elif payload.startswith("reject:"):
            rejects += 1

    seller_deals = [deals_by_seller.get(a, 0) for a in sorted(sellers)]
    buyer_deals = [deals_by_buyer.get(a, 0) for a in sorted(buyers)]

    return {
        "buy_requests": buys,
        "deals": sold,
        "rejects": rejects,
        "deal_rate": sold / buys if buys else 0.0,
        "delivery_rate": receives / sends if sends else 0.0,
        "starved_buyers": sum(1 for v in buyer_deals if v == 0),
        "starved_sellers": sum(1 for v in seller_deals if v == 0),
        "gini_buyers": gini(buyer_deals),
        "gini_sellers": gini(seller_deals),
    }


ROWS = [
    ("buy_requests", "Buy requests sent", "{:.0f}"),
    ("deals", "Deals closed", "{:.0f}"),
    ("deal_rate", "deal_rate (headline metric)", "{:.3f}"),
    ("delivery_rate", "delivery_rate", "{:.3f}"),
    ("starved_buyers", "Buyers with zero deals", "{:.0f}"),
    ("starved_sellers", "Sellers with zero deals", "{:.0f}"),
    ("gini_buyers", "Gini across buyers", "{:.3f}"),
    ("gini_sellers", "Gini across sellers", "{:.3f}"),
]


def main() -> int:
    """Print a side-by-side comparison of a baseline and a treatment trace."""
    if len(sys.argv) != 3:
        print(__doc__)
        return 1

    base = summarize(sys.argv[1])
    treat = summarize(sys.argv[2])

    print(f"{'':<30}{'baseline':>12}{'drop=0.05':>12}{'change':>12}")
    print("-" * 66)
    for key, label, fmt in ROWS:
        b, t = base[key], treat[key]
        if b:
            change = f"{(t - b) / b * 100:+.1f}%"
        else:
            change = f"{t - b:+.0f}" if t != b else "0"
        print(f"{label:<30}{fmt.format(b):>12}{fmt.format(t):>12}{change:>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
