# SPDX-License-Identifier: Apache-2.0
"""Re-run the baseline/treatment pair across several seeds.

One paired run is an anecdote. This checks whether the direction of the
``deal_rate`` change is stable, or an artifact of ``seed: 42``.

Example::

    python seed_sweep.py 42 43 44 45 46 47 48 49
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from analyze import summarize

BASELINE = Path("scenarios/marketplace.yaml")


def run(seed: int, drop: float, workdir: Path) -> dict[str, object]:
    """Run the marketplace scenario at one seed and drop rate; summarize it."""
    config = yaml.safe_load(BASELINE.read_text())
    config["seed"] = seed
    config["failures"]["message_drop"] = drop
    config["name"] = f"sweep_{seed}_{drop}"

    scenario = workdir / f"{config['name']}.yaml"
    trace = workdir / f"{config['name']}.jsonl"
    scenario.write_text(yaml.safe_dump(config))
    subprocess.run(
        ["nest", "run", str(scenario), "-o", str(trace)],
        capture_output=True,
        check=True,
    )
    return summarize(trace)


def main() -> int:
    """Print a per-seed comparison of deal_rate, volume, and starved buyers."""
    seeds = [int(a) for a in sys.argv[1:]] or [42, 43, 44, 45, 46, 47, 48, 49]
    print(f"{'seed':>5}{'deal_rate':>11}{'deal_rate':>11}{'buys':>8}{'buys':>8}{'starved':>9}")
    print(f"{'':>5}{'(base)':>11}{'(drop)':>11}{'(base)':>8}{'(drop)':>8}{'(drop)':>9}")
    print("-" * 52)

    risen = 0
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for seed in seeds:
            base = run(seed, 0.0, workdir)
            treat = run(seed, 0.05, workdir)
            if treat["deal_rate"] > base["deal_rate"]:
                risen += 1
            print(
                f"{seed:>5}{base['deal_rate']:>11.3f}{treat['deal_rate']:>11.3f}"
                f"{base['buy_requests']:>8}{treat['buy_requests']:>8}"
                f"{treat['starved_buyers']:>9}"
            )

    print(f"\ndeal_rate rose in {risen}/{len(seeds)} seeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
