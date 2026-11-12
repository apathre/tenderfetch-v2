"""
tests/test_sector_filter.py

Real-world-style tender titles the power-sector filter must keep (MUST_PASS)
or drop (MUST_FAIL). Run after any edit to core/sector_filter.py:

    python tests/test_sector_filter.py      # plain run, exits 1 on failure
    pytest tests/                           # also works if pytest is installed

When a genuine tender is wrongly skipped (or junk gets through), add its
title here first, then adjust the keyword lists until everything passes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.sector_filter import is_relevant, is_title_possibly_relevant  # noqa: E402

MUST_PASS = [
    # solar
    "Development of 500 MW Solar Park at Bikaner",
    "EPC for 100 MW grid connected solar PV plant",
    "EPC for 10 MW Floating Solar Plant on Omkareshwar reservoir",
    "Setting up of Rooftop Solar on government buildings under RESCO mode",
    "Supply of 2 GW solar modules",
    "Selection of Solar Power Developers for 1200 MW ISTS-connected projects",
    "Design, Supply, Installation and Commissioning of 5MWp ground mounted solar plant",
    "Selection of developers for agrivoltaic projects under PM-KUSUM Component A",
    # wind
    "EPC for 300 MW Wind Power Project in Gujarat",
    "Supply of WTGs for 50 MW wind farm",
    "Development of 500 MW offshore wind project off Tamil Nadu coast",
    "EPC for wind-solar hybrid project of 450 MW",
    "Repowering of 30 MW wind farm at Muppandal",
    # hydro / pumped storage
    "EPC for 60 MW Hydro Electric Project",
    "EPC for Small Hydro Project 24 MW",
    "Setting up of 1200 MW Pumped Storage Project",
    "Civil and hydro mechanical works for 1000 MW PSP",
    "Renovation and Modernisation of 4x30 MW hydel units",
    # storage
    "Selection of developer for 250 MW/500 MWh BESS on BOO basis",
    "Selection of BESS developer under VGF",
    "Setting up of 500 MWh Battery Energy Storage System",
    "Selection of BESPD for 1000 MW/2000 MWh energy storage on tariff basis",
    # firm / hybrid
    "Selection of developers for 1500 MW FDRE power under tariff based competitive bidding",
    "RTC power supply from 400 MW renewable energy projects - RfS",
    # green molecules
    "Supply of electrolysers for green hydrogen plant",
    "Setting up of green ammonia plant",
    "Selection of developer for green methanol production facility",
    "Setting up of 10 MW electrolyzer based green hydrogen hub",
    # bioenergy / waste / others
    "Setting up of 5 MW biomass power plant",
    "Installation of compressed biogas plant of 10 TPD",
    "EPC for waste to energy plant",
    "Development of geothermal power project in Ladakh",
    # thermal
    "EPC for 2x800 MW supercritical thermal power project",
    "EPC package for FGD system at 1320 MW thermal power station",
    # transmission
    "Setting up of 400 kV substation on TBCB basis",
    "Establishment of transmission system for evacuation of power from RE parks",
    "Construction of 765 kV D/C transmission line",
    "Supply of 315 MVA power transformers",
    "Supply, erection and commissioning of 220kV GIS substation",
    "Supply of conductors for 400 kV transmission line",
    "Request for Proposal Document for selection of Bidder as Transmission Service Provider "
    "to establish Inter-State Transmission System for Evacuation of Power from Rajasthan REZ Ph-V",
    "RfQ for selection of Bidder as TSP for 765 kV Ananthapuram-III Pooling Station",
    # land
    "Land acquisition for 1000 MW solar park",
    "Procurement of land for setting up of wind power project",
]

MUST_FAIL = [
    "Consultancy Services for Authoritys Engineer for Upgradation of Chitrod-Rapar-Balasar "
    "section of NH-927C to two-lane with paved shoulders from design km 0.00 to km 57.848 "
    "in the State of Gujarat on EPC Mode",
    "Construction of hostel building for boys at IIT campus on EPC basis",
    "Four laning of NH-48 on EPC mode",
    "Setting up of a library at district headquarters",
    "Hiring of vehicles for official use",
    "Supply and installation of solar street lights in villages",
    "Installation of solar water heaters in hostels",
    "Supply of hydrogen gas cylinders for laboratory",
    "Supply of hydrogen peroxide",
    "Annual maintenance contract for UPS batteries",
    "Construction of boundary wall around office premises",
    "Supply of computer peripherals",
    "Development of mobile application for citizen services",
    "Hydro test of water pipeline at treatment plant",
    "Purchase of microwave oven for canteen",
    "Request for Proposal for engagement of consultant for office renovation",
    "",
]


def test_must_pass():
    misses = [t for t in MUST_PASS if not is_relevant(t)]
    assert not misses, "Genuine power tenders rejected:\n  " + "\n  ".join(misses)


def test_must_fail():
    leaks = [t for t in MUST_FAIL if is_relevant(t)]
    assert not leaks, "Non-power tenders accepted:\n  " + "\n  ".join(leaks)


def test_title_prefilter_never_drops_a_genuine_title():
    # stage 1 must be at least as loose as stage 2
    misses = [t for t in MUST_PASS if not is_title_possibly_relevant(t)]
    assert not misses, "Stage-1 prefilter drops genuine titles:\n  " + "\n  ".join(misses)


if __name__ == "__main__":
    failed = 0
    for fn in (test_must_pass, test_must_fail, test_title_prefilter_never_drops_a_genuine_title):
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}\n{e}")
    print(f"\n{len(MUST_PASS)} must-pass, {len(MUST_FAIL)} must-fail titles checked")
    sys.exit(1 if failed else 0)
