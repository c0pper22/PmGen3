"""
RemoteTech API Client
=====================
A Python client for interacting with the RemoteTech (C4990_RTS) web application.

Usage:
    api = RemoteTechAPI(company=REMOTETECH_COMPANY)
    api.login("username", "password")
    # ... subsequent API calls ...
"""

import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REMOTETECH_COMPANY = "ibsprod"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _ViewStateParser(HTMLParser):
    """Extracts __VIEWSTATE and __VIEWSTATEGENERATOR hidden fields."""

    def __init__(self) -> None:
        super().__init__()
        self.viewstate: Optional[str] = None
        self.viewstate_generator: Optional[str] = None
        self.event_validation: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "input":
            return
        attr_dict = dict(attrs)
        name = attr_dict.get("name", "")
        value = attr_dict.get("value", "")
        if name == "__VIEWSTATE":
            self.viewstate = value
        elif name == "__VIEWSTATEGENERATOR":
            self.viewstate_generator = value
        elif name == "__EVENTVALIDATION":
            self.event_validation = value


def _local_tz_offset_minutes() -> int:
    """Return the local timezone offset from UTC in minutes (e.g. -240 for EDT)."""
    local_now = datetime.now(timezone.utc).astimezone()
    offset = local_now.utcoffset()
    if offset is None:
        return 0
    return int(offset.total_seconds() / 60)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class LoginResult:
    success: bool
    message: str = ""
    redirected_url: Optional[str] = None


@dataclass
class Call:
    """A single active call from the user's queue (pcalls.aspx table row)."""

    call_number: str          # e.g. "SC43848"
    call_id: str              # e.g. "42918" (numeric ID extracted from link href)
    location: str             # e.g. "Indiana Business Solutions NP"
    status: str               # e.g. "Pending"
    location_remarks: str     # e.g. ""
    description: str          # e.g. "test"
    make_model: str           # e.g. "99999999999-NP"
    est_start: str            # e.g. "6/22/2026 8:32 AM"
    address: str              # e.g. "4045 Vincennes Rd, Indianapolis"
    detail_url: str = ""      # Full URL to the call-details page


@dataclass
class PartLookupResult:
    """A single material/part match from the materialitem lookup API."""

    item_id: int              # e.g. 5425
    part_number: str          # e.g. "600N03611"
    description: str          # e.g. "Feed Rolls (HCF)"
    available: int            # e.g. 1
    pref_mfg_number: str      # e.g. "600N03611"


@dataclass
class AddedPartResult:
    """The material line item returned after successfully adding a part to a call."""

    call_inventory_id: int        # ``RTCallInventoryID``
    call_material_bin_id: int     # ``CallMaterialBinID``
    item_id: int                  # ``ItemID``
    part_number: str              # ``Item`` — e.g. "600N03611"
    description: str              # ``Description``
    quantity: float               # ``Quantity``
    bin: str                      # ``Bin``
    bin_id: int                   # ``BinID``
    warehouse: str                # ``Warehouse``
    warehouse_id: int             # ``WarehouseID``
    usage_status_code: str        # ``UsageStatusCode`` — "USED" or "NEEDED"
    delivery_method_id: int       # ``DeliveryMethodID`` — 0 when not set
    bill: bool                    # ``Bill``
    system_computed_price: float  # ``SystemComputedPrice``


# -- Enumerated constants ---------------------------------------------------
# (Using simple int/str constants rather than enums for ergonomic use with
#  the JSON API.  Can be passed directly to methods.)

class DeliveryMethod:
    """``DeliveryMethodID`` values for ``add_part_to_call``."""
    PICK_UP = 1
    SHIP_TO_CUSTOMER = 2
    SHIP_TO_TECH = 3


class UsageStatus:
    """``UsageStatusID`` values for ``add_part_to_call``."""
    USED = 1
    NEEDED = 2


# ---------------------------------------------------------------------------
# API Client
# ---------------------------------------------------------------------------

class RemoteTechAPI:
    """Synchronous HTTP client for the RemoteTech web API.

    Maintains a ``requests.Session`` so cookies (ASP.NET_SessionId, auth,
    etc.) are preserved across calls.
    """

    BASE_URL = "https://dgi17.ecihosted.com"
    APP_PATH = "/C4990_RTS"

    def __init__(
        self,
        base_url: str = BASE_URL,
        app_path: str = APP_PATH,
        company: str = "ibsprod",
        user_agent: Optional[str] = None,
        min_delay: float = 0.5,
        max_delay: float = 2.5,
        request_timeout: float = 30.0,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
    ) -> None:
        """Initialise the API client.

        Parameters
        ----------
        min_delay : float
            Minimum seconds to wait between HTTP requests (adds jitter).
        max_delay : float
            Maximum additional jitter seconds between requests.
        request_timeout : float
            Timeout in seconds for every HTTP call.
        max_retries : int
            Maximum retry attempts on 429 / 5xx responses.
        retry_backoff : float
            Multiplier for exponential backoff between retries.
        """
        self._base_url = base_url.rstrip("/")
        self._app_path = app_path.rstrip("/")
        self._company = company

        # -- Safety / anti-bot settings --
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._request_timeout = request_timeout
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._last_request_time: float = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) "
                    "Gecko/20100101 Firefox/152.0"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                # Modern browser fetch metadata — missing these is a bot fingerprint
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
            }
        )
        # Pre-set the company cookie so it's always sent
        self.session.cookies.set("SCompany", company, domain="dgi17.ecihosted.com")

        self._logged_in = False
        self._username: Optional[str] = None
        self._queue_id: Optional[str] = None

    # -- Safety: throttling & retry ---------------------------------------

    def _throttle(self) -> None:
        """Enforce a random delay between requests so we don't look like a bot.

        Sleeps if the last request was less than ``_min_delay`` seconds ago.
        Adds random jitter up to ``_max_delay``.
        """
        elapsed = time.monotonic() - self._last_request_time
        min_wait = max(0.0, self._min_delay - elapsed)
        jitter = random.uniform(0, self._max_delay - self._min_delay)
        total_wait = min_wait + jitter
        if total_wait > 0:
            time.sleep(total_wait)

    def _mark_request(self) -> None:
        """Record that a request just completed (call after every HTTP round-trip)."""
        self._last_request_time = time.monotonic()

    def _retry_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Perform an HTTP request with retry + exponential backoff on server errors.

        Retries on HTTP 429 (Too Many Requests), 5xx status codes, timeouts,
        and connection errors.  Raises the last exception if all retries are
        exhausted.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self.session.request(
                    method=method,
                    url=url,
                    timeout=self._request_timeout,
                    **kwargs,
                )
                # Retry on rate-limit or transient server errors
                if resp.status_code in (429, 502, 503, 504):
                    if attempt < self._max_retries:
                        backoff = self._retry_backoff ** attempt
                        time.sleep(backoff + random.uniform(0, 1))
                        continue
                return resp
            except requests.Timeout as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    backoff = self._retry_backoff ** attempt
                    time.sleep(backoff + random.uniform(0, 1))
                continue
            except requests.ConnectionError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    backoff = self._retry_backoff ** attempt
                    time.sleep(backoff + random.uniform(0, 1))
                continue
        # All retries exhausted
        raise last_exc  # type: ignore[misc]

    # -- URL helpers --------------------------------------------------------

    def _url(self, path: str) -> str:
        """Build a full URL from an app-relative path."""
        return urljoin(f"{self._base_url}{self._app_path}/", path.lstrip("/"))

    # -- Authentication -----------------------------------------------------

    @property
    def is_logged_in(self) -> bool:
        return self._logged_in

    def login(self, username: str, password: str) -> LoginResult:
        """Authenticate against the RemoteTech login page.

        Parameters
        ----------
        username : str
            The user name (``txtUserName`` field).
        password : str
            The password (``txtPassword`` field).

        Returns
        -------
        LoginResult
        """
        login_url = self._url("plogin.aspx")

        # ---- Step 1: GET the login page to obtain ViewState & session cookie ----
        self._throttle()
        get_resp = self._retry_request(
            "GET",
            login_url,
            headers={
                "Referer": login_url,
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self._mark_request()
        get_resp.raise_for_status()

        # Parse hidden ASP.NET fields
        parser = _ViewStateParser()
        parser.feed(get_resp.text)
        parser.close()

        viewstate = parser.viewstate or ""
        viewstate_generator = parser.viewstate_generator or ""
        event_validation = parser.event_validation or ""

        # ---- Step 2: POST the login form ----------------------------------------
        tz_offset = _local_tz_offset_minutes()

        form_data = {
            "_TZ": str(tz_offset),
            "__LASTFOCUS": "",
            "__VIEWSTATE": viewstate,
            "__VIEWSTATEGENERATOR": viewstate_generator,
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "txtUserName": username,
            "txtPassword": password,
            "txtCompany": self._company,
            "btnLogin": "Login",
            "urlHash": "",
        }

        # Include EVENTVALIDATION only when present (some ASP.NET pages omit it)
        if event_validation:
            form_data["__EVENTVALIDATION"] = event_validation

        self._throttle()
        post_resp = self._retry_request(
            "POST",
            login_url,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self._base_url,
                "Referer": login_url,
                "Upgrade-Insecure-Requests": "1",
            },
            allow_redirects=True,
        )
        self._mark_request()
        post_resp.raise_for_status()

        # ---- Step 3: Interpret the result ---------------------------------------
        final_url = post_resp.url
        # If we were redirected away from plogin.aspx, login likely succeeded.
        redirected = "plogin.aspx" not in final_url.lower()

        # Detect common ASP.NET failure indicators in the response body
        text = post_resp.text
        if "Invalid" in text or "failed" in text.lower():
            self._logged_in = False
            return LoginResult(
                success=False,
                message="Login failed — check credentials or company.",
                redirected_url=final_url if redirected else None,
            )

        if redirected:
            self._logged_in = True
            self._username = username
            return LoginResult(
                success=True,
                message="Login successful.",
                redirected_url=final_url,
            )

        # Still on login page — probably bad credentials
        self._logged_in = False
        return LoginResult(
            success=False,
            message="Login failed — still on login page.",
            redirected_url=None,
        )

    # -- Calls --------------------------------------------------------------

    def get_users_active_calls(self) -> list[Call]:
        """Return all active calls currently in the user's queue.

        Corresponds to the **pcalls.aspx** page (the "Calls" PDA view).

        Returns
        -------
        list[Call]
            May be empty if no calls are queued.
        """
        url = self._url("online/pcalls.aspx")
        self._throttle()
        resp = self._retry_request(
            "GET",
            url,
            headers={
                "Referer": self._url("manifestloader/loadmanifest.aspx"),
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self._mark_request()
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract the queue ID for subsequent API calls that need the Rtagent header
        queue_input = soup.find("input", id="_iQueueID")
        if queue_input:
            self._queue_id = queue_input.get("value", "")

        table = soup.find("table", id="lstCalls")
        if table is None:
            return []

        calls: list[Call] = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if not cells:
                continue  # skip header row (<th> only)

            # Each data row has exactly 8 cells in the order:
            #   Call | Location | Status | Location Remarks | Description |
            #   Make/Model | Est Start | Address
            if len(cells) < 8:
                continue

            # Cell 0 – Call number + link
            call_link = cells[0].find("a")
            call_number = call_link.get_text(strip=True) if call_link else cells[0].get_text(strip=True)
            call_href = call_link.get("href", "") if call_link else ""
            call_id = ""
            if call_href:
                # href looks like  ../calldetails/#/42918
                m = re.search(r"/(\d+)", call_href)
                if m:
                    call_id = m.group(1)
            # Build the full detail URL
            detail_url = ""
            if call_href:
                detail_url = urljoin(url, call_href)

            calls.append(Call(
                call_number=call_number,
                call_id=call_id,
                location=cells[1].get_text(strip=True),
                status=cells[2].get_text(strip=True),
                location_remarks=cells[3].get_text(strip=True),
                description=cells[4].get_text(strip=True),
                make_model=cells[5].get_text(strip=True),
                est_start=cells[6].get_text(strip=True),
                address=cells[7].get_text(strip=True),
                detail_url=detail_url,
            ))

        return calls

    # -- Parts / Materials --------------------------------------------------

    def part_number_lookup(
        self,
        part_number: str,
        count: int = 5,
        skip: int = 0,
        bin_search: bool = True, #true = only users bin / false = include all bins + Inventory 
        queue_id: Optional[str] = None,
        rtuser: Optional[str] = None,
    ) -> Optional[PartLookupResult]:
        """Look up a part number in the RemoteTech materials catalog.

        Hits the Angular ``materialitem`` JSON endpoint.  Returns the
        *exact* match when one is found, or ``None``.

        Parameters
        ----------
        part_number : str
            The part number to search for (e.g. ``"600N03611"``).
        count : int
            Maximum results to return (default 5).
        skip : int
            Results to skip for pagination (default 0).
        bin_search : bool
            Whether to include bin/location data (default True).
        queue_id : str | None
            Override the ``Rtagent`` header (auto-detected from
            ``get_users_active_calls`` if called first).
        rtuser : str | None
            Override the ``Rtuser`` header (set from login username
            automatically).

        Returns
        -------
        PartLookupResult | None
        """
        queue = queue_id or self._queue_id or ""
        user = rtuser or self._username or ""

        params = {
            "query": part_number,
            "count": str(count),
            "skip": str(skip),
            "bin": "true" if bin_search else "false",
        }
        url = self._url("api/lookups/materialitem")

        self._throttle()
        resp = self._retry_request(
            "GET",
            url,
            params=params,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Rtagent": queue,
                "Rtuser": user,
                "Referer": self._url("calldetails/"),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            },
        )
        self._mark_request()
        resp.raise_for_status()

        data = resp.json()
        exact = data.get("ExactItemMatch")
        if not exact:
            return None

        return PartLookupResult(
            item_id=exact.get("ItemID", 0),
            part_number=exact.get("Item", ""),
            description=exact.get("Description", ""),
            available=exact.get("Available", 0),
            pref_mfg_number=exact.get("PrefMfgNumber", ""),
        )

    def add_part_to_call(
        self,
        call_id: str,
        item_id: int,
        bin_id: int,
        quantity: int = 1,
        delivery_method_id: int = DeliveryMethod.PICK_UP,
        usage_status_id: int = UsageStatus.USED,
        bill: bool = True,
        discount: float = 0.0,
        queue_id: Optional[str] = None,
        rtuser: Optional[str] = None,
    ) -> AddedPartResult:
        """Add a material/part to an existing call.

        Parameters
        ----------
        call_id : str
            The **numeric** call ID (e.g. ``"42918"``), *not* the SC number.
        item_id : int
            ``ItemID`` from a ``PartLookupResult``.
        bin_id : int
            The bin ID (e.g. 130).
        quantity : int
            Quantity to add (default 1).
        delivery_method_id : int
            ``DeliveryMethod.PICK_UP`` (1), ``.SHIP_TO_CUSTOMER`` (2), or
            ``.SHIP_TO_TECH`` (3).
        usage_status_id : int
            ``UsageStatus.USED`` (1) or ``UsageStatus.NEEDED`` (2).
        bill : bool
            Whether the part is billable (default True).
        discount : float
            Discount percentage (default 0.0).
        queue_id : str | None
            Override the ``Rtagent`` header.
        rtuser : str | None
            Override the ``Rtuser`` header.

        Returns
        -------
        AddedPartResult
        """
        queue = queue_id or self._queue_id or ""
        user = rtuser or self._username or ""

        url = self._url(f"api/calls/{call_id}/materials")

        body = {
            "ItemID": item_id,
            "Price": {},
            "Quantity": quantity,
            "BinID": bin_id,
            "DeliveryMethodID": delivery_method_id,
            "UsageStatusID": usage_status_id,
            "Bill": bill,
            "Amount": {},
            "Discount": discount,
        }

        self._throttle()
        resp = self._retry_request(
            "POST",
            url,
            json=body,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=utf-8",
                "Rtagent": queue,
                "Rtuser": user,
                "Origin": self._base_url,
                "Referer": self._url("calldetails/"),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            },
        )
        self._mark_request()
        resp.raise_for_status()

        # The API returns a list — grab the first (and usually only) item
        items = resp.json()
        if not items:
            raise ValueError("add_part_to_call returned an empty response array")

        item = items[0]
        return AddedPartResult(
            call_inventory_id=item.get("RTCallInventoryID", 0),
            call_material_bin_id=item.get("CallMaterialBinID", 0),
            item_id=item.get("ItemID", 0),
            part_number=item.get("Item", ""),
            description=item.get("Description", ""),
            quantity=float(item.get("Quantity", 0)),
            bin=item.get("Bin", ""),
            bin_id=item.get("BinID", 0),
            warehouse=item.get("Warehouse", ""),
            warehouse_id=item.get("WarehouseID", 0),
            usage_status_code=item.get("UsageStatusCode", ""),
            delivery_method_id=item.get("DeliveryMethodID", 0),
            bill=bool(item.get("Bill", False)),
            system_computed_price=float(item.get("SystemComputedPrice", 0)),
        )

    def edit_part_on_call(
        self,
        call_id: str,
        call_material_bin_id: int,
        item_id: int,
        part_number: str,
        description: str,
        bin_id: int,
        quantity: float = 1,
        usage_status_id: int = UsageStatus.USED,
        serial_number: str = "",
        notes: str = "",
        discount: float = 0.0,
        server_detail_id: int = 1,
        queue_id: Optional[str] = None,
        rtuser: Optional[str] = None,
    ) -> AddedPartResult:
        """Update an existing material line on a call (quantity, status, etc.).

        Sends the **full** material object back to the API — all fields are
        required.  Most values can be sourced from the ``AddedPartResult``
        returned by ``add_part_to_call``.

        Parameters
        ----------
        call_id : str
            The **numeric** call ID (e.g. ``"42918"``).
        call_material_bin_id : int
            ``CallMaterialBinID`` from a previous ``AddedPartResult``
            (e.g. 14438).  This identifies *which* line to update.
        item_id : int
            ``ItemID`` for the part.
        part_number : str
            The part number string (``Item`` field).
        description : str
            Part description.
        bin_id : int
            Bin ID.
        quantity : float
            New quantity (default 1).
        usage_status_id : int
            ``UsageStatus.USED`` (1) or ``UsageStatus.NEEDED`` (2).
        serial_number : str
            Serial number if the part is serialized.
        notes : str
            Optional notes.
        discount : float
            Discount percentage (default 0.0).
        server_detail_id : int
            Server detail ID — purpose unclear; default 1 as observed.
        queue_id : str | None
            Override the ``Rtagent`` header.
        rtuser : str | None
            Override the ``Rtuser`` header.

        Returns
        -------
        AddedPartResult
            The updated material line from the API response.
        """
        queue = queue_id or self._queue_id or ""
        user = rtuser or self._username or ""

        url = self._url(f"api/calls/{call_id}/materials/{call_material_bin_id}")

        body = {
            "ItemID": item_id,
            "ServerDetailID": server_detail_id,
            "UsageStatusID": usage_status_id,
            "Item": part_number,
            "Description": description,
            "Quantity": quantity,
            "Serialized": bool(serial_number),
            "SerialNumber": serial_number,
            "BinID": bin_id,
            "Notes": notes,
            "CallMaterialBinID": call_material_bin_id,
            "Price": {},
            "Discount": discount,
            "Amount": {},
        }

        self._throttle()
        resp = self._retry_request(
            "POST",
            url,
            json=body,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json;charset=utf-8",
                "Rtagent": queue,
                "Rtuser": user,
                "Origin": self._base_url,
                "Referer": self._url("calldetails/"),
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
            },
        )
        self._mark_request()
        resp.raise_for_status()

        item = resp.json()
        return AddedPartResult(
            call_inventory_id=item.get("RTCallInventoryID", 0),
            call_material_bin_id=item.get("CallMaterialBinID", 0),
            item_id=item.get("ItemID", 0),
            part_number=item.get("Item", ""),
            description=item.get("Description", ""),
            quantity=float(item.get("Quantity", 0)),
            bin=item.get("Bin", ""),
            bin_id=item.get("BinID", 0),
            warehouse=item.get("Warehouse", ""),
            warehouse_id=item.get("WarehouseID", 0),
            usage_status_code=item.get("UsageStatusCode", ""),
            delivery_method_id=item.get("DeliveryMethodID", 0),
            bill=bool(item.get("Bill", False)),
            system_computed_price=float(item.get("SystemComputedPrice", 0)),
        )

    def logout(self) -> None:
        """Clear session state (does not call a server logout endpoint)."""
        self._logged_in = False
        self.session.cookies.clear()
        self.session.cookies.set("SCompany", self._company, domain="dgi17.ecihosted.com")