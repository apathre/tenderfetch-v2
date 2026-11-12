"""
tests/test_psu_parsers.py

Offline checks for scrapers/psu_list_scrapers.py against HTML shaped like
each site's real page (structure taken from the Probe Sites run of
12 Nov 2026). No network, no Chrome: a fake driver serves the HTML.

    python tests/test_psu_parsers.py
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# selenium isn't needed offline; stub it if missing
try:
    import selenium  # noqa: F401
except ImportError:
    for n in ["selenium", "selenium.webdriver", "selenium.webdriver.remote",
              "selenium.webdriver.remote.webdriver"]:
        sys.modules[n] = types.ModuleType(n)
    sys.modules["selenium.webdriver.remote.webdriver"].WebDriver = object

import scrapers.psu_list_scrapers as m  # noqa: E402

m.T_LOAD = m.T_DETAIL = 0
m.time.sleep = lambda s: None


class FakeDriver:
    def __init__(self, pages):
        self.pages, self.page_source, self.current_url = pages, "", ""

    def get(self, url):
        self.current_url = url
        self.page_source = next((html for key, html in self.pages.items() if key in url), "<html></html>")

    def execute_script(self, *_):
        return None


SRC = lambda base: {"key": "X", "name": "X", "base_url": base}  # noqa: E731

POWERGRID_LIST = """<table id="b_gData"><tr><th>#</th><th>Loc</th><th>Ref/Title</th><th>Doc</th><th>Pub</th><th>View</th><th>Corr</th></tr>
<tr><td>1</td><td>NARWAL</td><td>NR2/NT/W-CIVIL/DOM/J01/26/15230 / Construction of 400 kV substation bay</td>
<td>Fri, 11-Dec-2026 11:00 AM / Mon, 14-Dec-2026 11:30 AM</td><td>Thu, 12-Nov-2026 11:58 AM</td>
<td><a href="view-published-tender-details.aspx?tid=abc">View</a></td><td></td></tr></table>"""
POWERGRID_DETAIL = """<table><tr><td>Tender Reference No / x</td><td>NR2/NT/W-CIVIL/DOM/J01/26/15230</td>
<td>Tender Title / y</td><td>Construction of 400 kV substation bay</td></tr>
<tr><td>Tender Description / z</td><td>Civil works for 400 kV bay extension at Narwal</td></tr>
<tr><td>Location of Work / w</td><td>Narwal</td><td>Pin Code</td><td>181101</td></tr></table>"""

NTPC_LIST = """<table id="TenderLists"><tr><th>S</th><th>Ref</th><th>Title</th><th>Src</th><th>Close</th><th>D</th></tr>
<tr><td>1</td><td>CS-1150-364A-9</td><td>EPC package for 1320 MW FGD system</td><td>Corporate Contracts</td>
<td>10 Dec 2026 3:00 PM 28 days left</td><td><a href="/NITDetails/NITs/30500">View</a></td></tr></table>"""
NTPC_DETAIL = """<table class="DtTable"><tr><td>Source of NIT :</td><td>Corporate Contracts</td></tr>
<tr><td>Brief NIT Description :</td><td>EPC package for 1320 MW FGD system at Lara STPP Stage-II</td></tr></table>
<table class="DtTable"><tr><td>EMD Cost :</td><td>Rs 2,50,00,000</td></tr><tr><td>Date Of Issue of NIT :</td><td>07/11/2026</td></tr>
<tr><td>Closing Date :</td><td>10/12/2026 :15:00</td></tr></table>"""

NGEL_LIST = """<table id="myTable"><tr><th>Sr</th><th>No</th><th>Desc</th><th>S</th><th>E</th><th>B</th><th>R</th></tr>
<tr><td>1</td><td>NRE-CS-5928-003(WTG)-9</td><td>SUPPLY AND INSTALLATION OF WIND TURBINE GENERATORS</td>
<td>22/06/2026</td><td>19/11/2026</td><td>19/11/2026</td>
<td><a href="/public/tender/1/7a/x.pdf">1 - Corrigendum</a><a href="/public/tender/1/7a/7a.pdf">NIT</a></td></tr></table>"""

THDC_LIST = """<table class="cols-4"><tr><th>S</th><th>Title</th><th>Last</th><th>D</th></tr>
<tr><td>1</td><td>EPC for 1000 MW Tehri PSP balance works (Tender No. THDCIL/CC-561)</td><td>2/12/2026</td>
<td><a href="/sites/default/files/tender/nit70.pdf">Download</a></td></tr></table>"""

PFCCL_HOME = """<a href="newsDetails.php?ID=2379">Request for Proposal Document for selection of Bidder as Transmission
Service Provider to establish Inter-State Transmission System for evacuation of power from Bikaner Complex</a>
<a href="newsDetails.php?ID=2355">Notice for Finance Advisor</a>"""
PFCCL_NEWS = """<a href="download/amendment-02.pdf">Amendment No. 2 (pdf file)</a>"""


def run(cls, base, pages, url_key="detail"):
    s = cls(FakeDriver(pages), SRC(base))
    org = s.fetch_org_list()[0]
    stubs, _ = s.fetch_tender_list_incremental(org["org_url"], set())
    assert stubs, f"{cls.__name__}: no stubs"
    return stubs, s.fetch_tender_detail(stubs[0]["detail_url"])


def test_nic_date():
    cases = {
        "Fri, 11-Dec-2026 11:00 AM": "11-Dec-2026 11:00 AM",
        "10 Dec 2026 3:00 PM 28 days left": "10-Dec-2026 03:00 PM",
        "10/12/2026 :15:00": "10-Dec-2026 03:00 PM",
        "2/12/2026": "02-Dec-2026",
        "rubbish": "",
    }
    bad = {k: (m.nic_date(k), v) for k, v in cases.items() if m.nic_date(k) != v}
    assert not bad, bad


def test_powergrid():
    stubs, rec = run(m.PowergridScraper, "https://apps.powergrid.in",
                     {"view-published-tender.aspx": POWERGRID_LIST, "details.aspx": POWERGRID_DETAIL})
    assert rec["Tender ID"] == "NR2/NT/W-CIVIL/DOM/J01/26/15230", rec
    assert rec["Title"] == "Construction of 400 kV substation bay", rec
    assert rec["Bid Submission End Date"] == "11-Dec-2026 11:00 AM", rec
    assert rec["Work Description"].startswith("Civil works"), rec
    assert rec["Location"] == "NARWAL", rec


def test_ntpc():
    stubs, rec = run(m.NTPCTenderScraper, "https://ntpctender.ntpc.co.in",
                     {"Index/Search": NTPC_LIST, "NITDetails": NTPC_DETAIL})
    assert rec["Tender ID"] == "NTPC-30500", rec
    assert rec["Tender Reference Number"] == "CS-1150-364A-9", rec
    assert rec["Bid Submission End Date"] == "10-Dec-2026 03:00 PM", rec
    assert rec["EMD Amount in Rs"] == "25000000", rec
    assert "Lara" in rec["Work Description"], rec


def test_ngel():
    stubs, rec = run(m.NGELScraper, "https://www.ngel.in", {"/tender": NGEL_LIST})
    assert rec["Tender ID"] == "NRE-CS-5928-003(WTG)-9", rec
    assert rec["Tender Detail URL"].endswith("/7a/7a.pdf"), rec
    assert rec["Bid Submission End Date"] == "19-Nov-2026", rec


def test_thdc():
    pages = {"tender?page=0": THDC_LIST}
    stubs, rec = run(m.THDCScraper, "https://thdc.co.in", pages)
    assert rec["Tender ID"] == "THDC-nit70", rec
    assert rec["Tender Reference Number"] == "Tender No. THDCIL/CC-561", rec


def test_pfccl():
    stubs, rec = run(m.PFCCLScraper, "https://www.pfcclindia.com",
                     {"index.php": PFCCL_HOME, "newsDetails": PFCCL_NEWS})
    assert len(stubs) == 1 and rec["Tender ID"] == "PFCCL-2379", (stubs, rec)
    assert "Amendment No. 2" in rec["Work Description"], rec


RECPDCL_TBCB = """<table class="table table-bordered"><tr><th>name</th></tr><tr><td></td></tr>
<tr><td>Request for Proposal Document for Selection of Bidder as Transmission Service Provider for 400 kV Nabinagar-Aurangabad line
<a href="/assets/data/pdf/NIT_Notification_Nabinagar_(English)_29102026.pdf">NIT Notification (English)</a>
<a href="/assets/data/pdf/RFP_Nabinagar_Aurangabad_29102026.pdf">RFP Document</a></td></tr></table>"""


def test_recpdcl():
    stubs, rec = run(m.RECPDCLScraper, "https://www.recpdcl.in", {"rectpcltender": RECPDCL_TBCB})
    assert rec["Tender ID"] == "RECPDCL-NIT_Notification_Nabinagar_(English)_29102026", rec
    assert rec["Title"].startswith("Request for Proposal Document") and "NIT Notification" not in rec["Title"], rec
    assert rec["Tender Category"] == "TBCB", rec


if __name__ == "__main__":
    failed = 0
    for fn in [v for k, v in dict(globals()).items() if k.startswith("test_")]:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e!r}"[:600])
    sys.exit(1 if failed else 0)
