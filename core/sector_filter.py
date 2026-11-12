"""
core/sector_filter.py

Keyword-based relevance filter, applied once in base_scraper.py's shared
scrape() loop so every scraper (CPPP, NTPC, SECI, SJVN, future PowerGrid —
anything built on BaseScraper) gets it automatically, with no per-scraper
changes needed. Also used by scripts/backfill_sheet_to_db.py and
scripts/purge_irrelevant_db_rows.py.

Restricts scraping to:
  1. Tariff-based / developer-selection tenders (DBFOT/BOO/BOOT/BOT/TBCB,
     VGF, RfS, PPA, etc.) for power generation — Thermal, Hydro (incl.
     small hydro, pumped storage), Wind (onshore/offshore), Solar (ground,
     park, rooftop, floating), BESS / energy storage, Hybrid / RTC, Green
     Hydrogen / Ammonia / Methanol, Bioenergy (biomass, CBG, waste-to-
     energy), Geothermal, Nuclear — or transmission line/substation build-out.
  2. EPC tenders for the same set of technologies/infrastructure.
  3. Land procurement for such projects.
  4. Equipment procurement for such projects.

A tender counts as relevant when its text matches >=1 TECH_KEYWORDS term
AND >=1 PURPOSE_KEYWORDS term — two independent buckets combined with AND,
not a single flat list. EXCLUDE_PHRASES (solar street lights, solar water
heaters, ...) are stripped from the text first, so they cannot supply the
tech match on their own.

Matching is case-insensitive, whole-word, accepts a plain plural "s", and
treats hyphens, slashes and line breaks as spaces ("wind-solar",
"waste-to-energy", "sub-station" all match their spaced forms).

tests/test_sector_filter.py holds real-world titles that must / must not
pass. Run it after any edit here:  python tests/test_sector_filter.py
Toggle SECTOR_FILTER_ENABLED to False to disable filtering entirely.
"""

import re

SECTOR_FILTER_ENABLED = True

# ── Technology / infrastructure bucket ───────────────────────────────────────
TECH_KEYWORDS = [
    # thermal
    "thermal power", "thermal plant", "thermal project", "super thermal",
    "thermal power station", "coal based power", "coal fired",
    "gas based power", "combined cycle", "ccgt", "fgd", "flue gas desulphurisation",
    "flue gas desulfurization",
    # hydro (bare "hydro" is deliberately absent — "hydro test" of pipelines)
    "hydro power", "hydropower", "hydro electric", "hydroelectric", "hydel",
    "hydro project", "hydro plant", "hydro station", "small hydro", "shp",
    "pumped storage", "pumped hydro", "psp", "run of river",
    # wind (onshore + offshore)
    "wind", "wtg", "offshore wind", "onshore wind",
    # solar (bare "solar" + EXCLUDE_PHRASES below for street lights etc.)
    "solar", "photovoltaic", "agrivoltaic", "agri pv",
    # storage
    "bess", "battery energy storage", "battery storage", "energy storage",
    "storage system",
    # hybrid / firm power
    "hybrid power", "hybrid energy", "hybrid project", "rtc power",
    "round the clock", "fdre", "firm and dispatchable", "peak power",
    # green molecules
    "hydrogen", "green ammonia", "ammonia plant", "green methanol",
    "e methanol", "electrolyser", "electrolyzer", "electrolysis",
    # bioenergy / waste / others
    "biomass", "biogas", "compressed biogas", "cbg", "bio cng", "bio energy",
    "bioenergy", "waste to energy", "wte", "geothermal", "tidal",
    "nuclear power", "small modular reactor",
    # generic generation
    "renewable energy", "renewable power", "re power", "re project", "green energy",
    "clean energy", "power plant", "power project", "power station",
    "generating station", "generation station", "mw", "gw", "mwh", "gwh",
    "mwp", "mwac", "mwdc",
    # transmission / grid
    "transmission line", "transmission system", "transmission project",
    "transmission scheme", "substation", "sub station", "switchyard",
    "grid station", "gss", "pooling station", "hvdc", "ehv", "kv", "mva",
    "statcom", "gis substation", "ists", "intra state transmission",
    "inter state transmission", "power evacuation",
]

# ── Purpose bucket: tariff-based / developer selection / EPC / land / equipment
PURPOSE_KEYWORDS = [
    # tariff-based / build-operate structures / developer selection
    "epc", "engineering procurement and construction", "engineering procurement construction",
    "engineering, procurement",
    "dbfot", "boo", "boot", "bot", "boo basis", "build own operate",
    "tariff based", "tariff", "tbcb", "turnkey", "bos", "balance of system",
    "balance of plant", "bop",
    "vgf", "viability gap", "rfs", "request for selection",
    "selection of developer", "selection of developers", "developer", "developers",
    "ppa", "power purchase agreement", "bess purchase agreement",
    "bpa", "e reverse auction", "reverse auction",
    # development / construction process — generic on their own, but the AND
    # with TECH_KEYWORDS keeps precision ("setting up of a library" never
    # matches — no tech keyword present)
    "setting up", "set up of", "development of", "establishment of",
    "installation of", "erection of", "commissioning of", "construction of",
    "design, supply", "design supply", "supply, installation", "supply installation",
    "supply erection", "sitc", "etc basis", "augmentation of", "repowering",
    "renovation and modernisation", "renovation and modernization", "r&m",
    # land
    "land acquisition", "land procurement", "land purchase", "land lease",
    "land for", "right of way", "row acquisition", "row compensation",
    # equipment
    "transformer", "switchgear", "turbine", "inverter", "pcs",
    "power conversion system", "solar module", "solar panel",
    "wind turbine generator", "wtg", "nacelle", "blade", "conductor",
    "insulator", "circuit breaker", "isolator", "electrolyser", "electrolyzer",
    "battery cell", "battery pack", "battery container", "tower package",
    "tower", "monopole", "lattice", "cable", "power cable", "boiler", "generator",
    "hydro mechanical", "penstock", "gates and hoist", "tracker", "module mounting",
    "reactor", "capacitor bank", "scada",
]

# Phrases that contain a tech word but are NOT power-sector projects. They are
# removed from the text before matching, so a tender about solar street
# lights only passes if it ALSO mentions real power-sector work.
EXCLUDE_PHRASES = [
    "solar street light", "solar street lighting", "solar streetlight",
    "solar light", "solar lighting", "solar lamp", "solar lantern",
    "solar high mast", "solar blinker", "solar traffic", "solar water heater",
    "solar water heating", "solar cooker", "solar dryer", "solar drier",
    "solar fencing", "solar fence", "solar inverter for ups",
    "wind breaker", "wind screen", "windscreen", "wind sock", "windsock",
    "hydrogen peroxide", "hydrogen gas cylinder", "hydrogen cylinder",
    "mw oven", "microwave",
]


def _norm(text: str) -> str:
    # hyphens, en/em dashes, slashes and any whitespace run → single space
    return re.sub(r"[\s\-–—/]+", " ", text or "").strip()


def _compile(keywords: list[str]) -> re.Pattern:
    # "s?" on each keyword so plain plurals match too (substation/substations,
    # electrolyser/electrolysers) without opening up false positives on short
    # acronyms — \bboos?\b still won't match inside "boost". Longest keywords
    # first so a phrase wins over its own prefix in the alternation.
    keys = sorted({_norm(k).lower() for k in keywords}, key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(re.escape(k) + "s?" for k in keys) + r")\b", re.IGNORECASE)


_TECH_RE = _compile(TECH_KEYWORDS)
_PURPOSE_RE = _compile(PURPOSE_KEYWORDS)
_EXCLUDE_RE = _compile(EXCLUDE_PHRASES)


def _prepare(*texts: str) -> str:
    combined = _norm(" ".join(t for t in texts if t))
    # "100 MW" / "100MW" / "400kV" → make the unit a standalone word
    combined = re.sub(r"(\d)(mw|gw|kv|mva|mwh|gwh|mwp)\b", r"\1 \2", combined, flags=re.IGNORECASE)
    return _EXCLUDE_RE.sub(" ", combined)


def is_relevant(*texts: str) -> bool:
    """True if the combined text matches >=1 tech keyword AND >=1 purpose
    keyword. Blank/empty input never matches. Always True when
    SECTOR_FILTER_ENABLED is False (filtering off)."""
    if not SECTOR_FILTER_ENABLED:
        return True
    combined = _prepare(*texts)
    if not combined.strip():
        return False
    return bool(_TECH_RE.search(combined)) and bool(_PURPOSE_RE.search(combined))


def is_title_possibly_relevant(title: str) -> bool:
    """Loose stage-1 check on the list-page title, before the detail page
    is fetched. Passes on EITHER a tech OR a purpose keyword, or if there is
    no title. The strict tech-AND-purpose test in is_relevant() still
    decides on the full detail text."""
    if not SECTOR_FILTER_ENABLED:
        return True
    if not title or not title.strip():
        return True
    t = _prepare(title)
    return bool(_TECH_RE.search(t)) or bool(_PURPOSE_RE.search(t))
