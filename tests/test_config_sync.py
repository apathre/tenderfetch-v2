"""
tests/test_config_sync.py

Guards the three places a source has to be registered, which are easy to
let drift apart when adding a portal:
  1. core/config.py SOURCES
  2. .github/scripts/resolve_sources.py CRON_TO_KEY
  3. .github/workflows/fetch_tenders.yml (schedule crons + dispatch options)

Also checks the org_include patterns keep the power utilities they are
meant to keep and drop the obvious non-power departments.

    python tests/test_config_sync.py
"""

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import CPSE_POWER_ORGS, SOURCES, STATE_POWER_ORGS  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "resolve_sources", ROOT / ".github" / "scripts" / "resolve_sources.py")
_rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rs)
CRON_TO_KEY = _rs.CRON_TO_KEY

WORKFLOW = (ROOT / ".github" / "workflows" / "fetch_tenders.yml").read_text(encoding="utf-8")
WF_CRONS = re.findall(r'-\s*cron:\s*"([^"]+)"', WORKFLOW)
_opts = re.search(r"options:\s*\n((?:\s+-\s*\S+\s*\n)+)", WORKFLOW)
WF_OPTIONS = re.findall(r"-\s*(\S+)", _opts.group(1)) if _opts else []

KEYS = [s["key"] for s in SOURCES]

STATE_KEEP = [
    "West Bengal State Electricity Distribution Company Limited",
    "West Bengal Power Development Corporation Limited",
    "Punjab State Power Corporation Limited",
    "Haryana Vidyut Prasaran Nigam Limited",
    "Uttar Haryana Bijli Vitran Nigam",
    "Jharkhand Urja Sancharan Nigam Limited",
    "HP State Electricity Board Ltd",
    "Uttarakhand Jal Vidyut Nigam Ltd",
    "GRIDCO Limited",
    "Odisha Hydro Power Corporation",
    "Jammu and Kashmir Power Development Department",
    "Assam Power Distribution Company Limited",
    "Odisha Renewable Energy Development Agency",
    "Energy CEE", "Assam Power Generation Company Limited",
    "MD (Power Transmisison Corporation of Uttarakhand Limited)", "UJVN Limited",
    "Jharkhand Urja Vikas Nigam Limited", "JSEB", "Director (UREDA)", "JREDA",
]
STATE_DROP = [
    "Public Works Department", "Municipal Corporation Kolkata", "Jal Nigam",
    "University of Calcutta", "Health and Family Welfare",
    "Food - Public Distribution and Consumer Affairs",
    "Executive Officer Nagar Panchayat Padli Gurjar", "CEO (Uttarakhand Rural Roads Development Agency)",
    "Director (Agriculture)", "Jharkhand Industrial Area Development Authority",
]
CPSE_KEEP = [
    "Damodar Valley Corporation", "North Eastern Electric Power Corporation Limited",
    "THDC India Limited", "Bharat Heavy Electricals Limited",
    "Nuclear Power Corporation of India Limited",
]
CPSE_DROP = ["Steel Authority of India Limited", "Airports Authority of India"]


def test_keys_unique():
    dupes = {k for k in KEYS if KEYS.count(k) > 1}
    assert not dupes, f"duplicate source keys: {dupes}"


def test_every_cron_maps_to_a_source():
    bad = {c: k for c, k in CRON_TO_KEY.items() if k not in KEYS}
    assert not bad, f"CRON_TO_KEY points at unknown keys: {bad}"


def test_workflow_crons_match_resolve_sources():
    assert set(WF_CRONS) == set(CRON_TO_KEY), (
        f"only in workflow: {set(WF_CRONS) - set(CRON_TO_KEY)}; "
        f"only in resolve_sources: {set(CRON_TO_KEY) - set(WF_CRONS)}")


def test_dispatch_options_list_every_source():
    missing = set(KEYS) - set(WF_OPTIONS)
    assert not missing, f"sources missing from workflow_dispatch options: {missing}"


def test_every_source_is_scheduled():
    unscheduled = set(KEYS) - set(CRON_TO_KEY.values())
    assert not unscheduled, f"sources with no cron: {unscheduled}"


def test_org_patterns():
    st, cp = re.compile(STATE_POWER_ORGS, re.I), re.compile(CPSE_POWER_ORGS, re.I)
    problems = [f"state pattern drops {n!r}" for n in STATE_KEEP if not st.search(n)]
    problems += [f"state pattern keeps {n!r}" for n in STATE_DROP if st.search(n)]
    problems += [f"CPSE pattern drops {n!r}" for n in CPSE_KEEP if not cp.search(n)]
    problems += [f"CPSE pattern keeps {n!r}" for n in CPSE_DROP if cp.search(n)]
    assert not problems, "\n  ".join(problems)


if __name__ == "__main__":
    failed = 0
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}\n  {e}")
    sys.exit(1 if failed else 0)
