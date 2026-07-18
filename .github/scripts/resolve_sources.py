"""
.github/scripts/resolve_sources.py

Decides which source key(s) the "scrape" matrix job should run for this
trigger, and writes them as a JSON array to $GITHUB_OUTPUT (consumed as
the matrix's "source_key" dimension in fetch_tenders.yml).

Three trigger shapes:
  - workflow_dispatch with a specific source chosen  -> run just that one,
    regardless of its "enabled" flag in core/config.py (an explicit manual
    pick is always honored — useful for testing a source before flipping
    it to enabled: True).
  - workflow_dispatch with "all" chosen               -> run every source
    currently enabled: True in core/config.py.
  - schedule (cron)                                   -> CRON_TO_KEY below
    maps the cron string that fired (github.event.schedule) to exactly one
    source key, which only runs if it's still enabled: True. Keep this map
    in sync with the `on.schedule` list in fetch_tenders.yml.
"""

import json
import os
import sys
from pathlib import Path

# repo root isn't on sys.path when this script is invoked by its file path
# (e.g. `python .github/scripts/resolve_sources.py`) — add it so
# `core.config` resolves regardless of how/where it's launched from.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.config import SOURCES

CRON_TO_KEY = {
    "30 0 * * *": "CPPP",         # 6:00 AM IST
    "0 1 * * *":  "MP",           # 6:30 AM IST
    "30 1 * * *": "UP",           # 7:00 AM IST
    "0 2 * * *":  "Rajasthan",    # 7:30 AM IST
    "30 2 * * *": "TN",           # 8:00 AM IST
    "0 3 * * *":  "Kerala",       # 8:30 AM IST
    "30 3 * * *": "Maharashtra",  # 9:00 AM IST
}


def resolve() -> list[str]:
    enabled_keys = {s["key"] for s in SOURCES if s.get("enabled", True)}

    input_source = os.environ.get("INPUT_SOURCE", "").strip()
    cron = os.environ.get("CRON_SCHEDULE", "").strip()

    if input_source and input_source != "all":
        return [input_source]

    if input_source == "all":
        return sorted(enabled_keys)

    if cron:
        key = CRON_TO_KEY.get(cron)
        return [key] if key and key in enabled_keys else []

    return []


if __name__ == "__main__":
    keys = resolve()
    print(f"Resolved source keys: {keys}")

    with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
        fh.write(f"sources={json.dumps(keys)}\n")
