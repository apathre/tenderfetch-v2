"""
core/sector_filter.py

Keyword-based relevance filter, applied once in base_scraper.py's shared
scrape() loop so every scraper (CPPP, NTPC, SECI, SJVN, future PowerGrid —
anything built on BaseScraper) gets it automatically, with no per-scraper
changes needed.

Restricts scraping to:
  1. Tariff-based tenders (DBFOT/BOO/BOOT/BOT/TBCB, etc.) for power
     generation (Thermal/Hydro/Wind/Solar/BESS/Hybrid/Green Hydrogen/
     Green Ammonia/Green Methanol/other new tech) or transmission
     line/substation build-out.
  2. EPC tenders for the same set of technologies/infrastructure.
  3. Land procurement for such projects.
  4. Equipment procurement for such projects.

A tender counts as relevant when its text matches >=1 TECH_KEYWORDS term
AND >=1 PURPOSE_KEYWORDS term — two independent buckets combined with AND,
not a single flat list. Toggle SECTOR_FILTER_ENABLED to False to disable
filtering entirely (e.g. while tuning the keyword lists).
"""

import re

SECTOR_FILTER_ENABLED = True

# ── Technology / infrastructure bucket ───────────────────────────────────────
TECH_KEYWORDS = [
    "thermal power", "thermal plant",
    "hydro power", "hydel", "hydro electric", "hydroelectric",
    "wind power", "wind energy", "wind farm",
    "solar power", "solar energy", "solar pv", "photovoltaic",
    "bess", "battery energy storage", "battery storage system",
    "hybrid power", "hybrid energy", "hybrid project",
    "green hydrogen", "green ammonia", "green methanol",
    "renewable energy", "renewable power", "re power",
    "power plant", "power project", "power station", "generation station",
    "transmission line", "transmission system", "transmission project",
    "substation", "sub-station", "switchyard", "grid station",
    "hvdc", "kv transmission", "kv line", "gis substation",
]

# ── Purpose bucket: tariff-based / EPC / land / equipment ──────────────────
PURPOSE_KEYWORDS = [
    # tariff-based / build-operate structures
    "epc", "engineering procurement and construction", "engineering, procurement",
    "dbfot", "boo", "boot", "bot", "build own operate", "build-own-operate",
    "tariff based", "tbcb", "turnkey", "bos", "balance of system",
    # development / construction process — generic on their own, but the AND
    # with TECH_KEYWORDS below keeps precision (e.g. "setting up of a
    # library" never matches — no tech keyword present)
    "setting up", "set up of", "development of", "establishment of",
    "installation of", "erection of", "commissioning of",
    # land
    "land acquisition", "land procurement", "land purchase",
    "right of way", "row acquisition",
    # equipment
    "transformer", "switchgear", "turbine", "inverter", "solar module",
    "solar panel", "wind turbine generator", "wtg", "conductor",
    "insulator", "circuit breaker", "isolator", "electrolyzer",
    "battery cell", "battery pack", "tower package",
]


def _compile(keywords: list[str]) -> re.Pattern:
    # "s?" on each keyword so plain plurals match too (substation/substations,
    # transformer/transformers, isolator/isolators, ...) without opening up
    # false positives on short acronyms — \bboos?\b still won't match inside
    # "boost" (boo+s leaves a non-boundary "t" right after, so that branch
    # fails; boo alone leaves "s" right after, also a non-boundary — the
    # required trailing \b rules out both).
    return re.compile(r"\b(" + "|".join(re.escape(k) + "s?" for k in keywords) + r")\b", re.IGNORECASE)


_TECH_RE = _compile(TECH_KEYWORDS)
_PURPOSE_RE = _compile(PURPOSE_KEYWORDS)


def is_relevant(*texts: str) -> bool:
    """True if the combined text matches >=1 tech keyword AND >=1 purpose
    keyword. Blank/empty input never matches. Always True when
    SECTOR_FILTER_ENABLED is False (filtering off)."""
    if not SECTOR_FILTER_ENABLED:
        return True
    combined = " ".join(t for t in texts if t)
    if not combined.strip():
        return False
    return bool(_TECH_RE.search(combined)) and bool(_PURPOSE_RE.search(combined))
