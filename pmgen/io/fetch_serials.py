from __future__ import annotations

from typing import List, Iterable, Dict
import re
import requests
import logging

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None  # type: ignore[misc,assignment]  # type: ignore[assignment]

BASE_URL = "https://eservice.toshiba-solutions.com"
LOGIN_PAGE = f"{BASE_URL}/Account/LogOn"
DEVICE_INDEX = f"{BASE_URL}/Device/Index"
DEVICE_INDEX_INACTIVE = f"{BASE_URL}/Device?tabIndex=1"

HEADERS_COMMON = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
        "Gecko/20100101 Firefox/128.0"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": LOGIN_PAGE,
}

# ─────────────────────────────────────────────────────────────
# Serial parsing (your existing code, kept intact)
# ─────────────────────────────────────────────────────────────
_SERIAL_RE = re.compile(r"\b[A-Z][A-Z0-9]{3}\d{5}\b", re.I)
_NO_CUSTOMER_ASSIGNED = "(No Customer Assigned)"
_IGNORED_CUSTOMER_VALUES = {"edit"}

def _normalize_serial(value: str) -> str:
    text = (value or "").strip().upper()
    return text if _SERIAL_RE.fullmatch(text) else ""

def _extract_serial(text: str) -> str:
    match = _SERIAL_RE.search(text or "")
    return _normalize_serial(match.group(0)) if match else ""

def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

def _normalize_customer_value(value: str) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if "no customer assigned" in text.lower():
        return _NO_CUSTOMER_ASSIGNED
    if text.lower() in _IGNORED_CUSTOMER_VALUES:
        return ""
    return text

def _customer_value_from_element(element) -> str:
    no_customer_el = element.select_one(".noCustomerName") if hasattr(element, "select_one") else None
    if no_customer_el is not None:
        value = _normalize_customer_value(no_customer_el.get_text(" ", strip=True))
        if value:
            return value
    return _normalize_customer_value(element.get_text(" ", strip=True))

def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out

def parse_serial_numbers(html: str) -> List[str]:
    """
    Extract device serials from the provided HTML string.

    Returns:
        A de-duplicated list of serials, preserving first-seen order.
    """
    if not isinstance(html, str) or not html:
        return []

    found: List[str] = []

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")

            # <div data-serial="CNAM66582">…</div>
            for el in soup.select("[data-serial]"):
                val = (el.get("data-serial") or "").strip()  # type: ignore[union-attr]
                serial = _normalize_serial(val)
                if serial:
                    found.append(serial)

            # hrefs with ?serial=XYZ or ?deviceSerial=XYZ
            for a in soup.find_all("a", href=True):
                href = a["href"]
                for key in ("serial", "deviceSerial"):
                    m = re.search(rf"(?:\?|&){key}=([^&#]+)", str(href))
                    if m:
                        cand = m.group(1).strip()
                        cand = re.sub(r"%2f|%2F|%20", "", cand)
                        serial = _normalize_serial(cand)
                        if serial:
                            found.append(serial)
        except Exception:
            logger.debug("BeautifulSoup parsing failed, falling back to regex sweep", exc_info=True)

    # Regex sweep for stragglers (JSON-inlined, plain text tables, etc.)
    for m in _SERIAL_RE.finditer(html):
        found.append(_normalize_serial(m.group(0)))

    return _dedupe_preserve_order([serial for serial in found if serial])

def _customer_from_header(row, serial: str) -> str:
    table = row.find_parent("table")
    if table is None:
        return ""

    header_row = None
    for candidate in table.find_all("tr"):
        if candidate.find("th"):
            header_row = candidate
            break
    if header_row is None:
        return ""

    headers = [_clean_text(cell.get_text(" ", strip=True)).lower() for cell in header_row.find_all(["th", "td"])]
    cells = row.find_all(["td", "th"], recursive=False)
    for index, header in enumerate(headers):
        if "customer" not in header or index >= len(cells):
            continue
        value = _normalize_customer_value(cells[index].get_text(" ", strip=True))
        if value and _extract_serial(value) != serial:
            return value
    return ""

def _customer_from_neighbor_cell(row, serial: str) -> str:
    cells = row.find_all(["td", "th"], recursive=False)
    if not cells:
        return ""

    texts = [_clean_text(cell.get_text(" ", strip=True)) for cell in cells]
    serial_index = next((index for index, text in enumerate(texts) if _extract_serial(text) == serial), -1)
    if serial_index < 0:
        return ""

    for text in texts[serial_index + 1:]:
        value = _normalize_customer_value(text)
        if value and _extract_serial(value) != serial:
            return value
    return ""

def _customer_from_row(row, serial: str) -> str:
    for element in row.select(".noCustomerName"):
        value = _customer_value_from_element(element)
        if value:
            return value

    customer_selectors = [
        ".deviceCustomers",
        '[class*="Customer"]',
        '[class*="customer"]',
        '[id*="Customer"]',
        '[id*="customer"]',
    ]
    for selector in customer_selectors:
        for element in row.select(selector):
            value = _customer_value_from_element(element)
            if value and _extract_serial(value) != serial:
                return value

    return _customer_from_header(row, serial) or _customer_from_neighbor_cell(row, serial)

def parse_customer_map(html: str) -> Dict[str, str]:
    """
    Parses HTML to create a mapping of { Serial_Number : Customer_Name }.
    """
    if not isinstance(html, str) or not html:
        return {}

    data_map: Dict[str, str] = {}

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            for row in soup.find_all("tr"):
                serial_el = row.select_one(".deviceSerialNumbers")
                serial = _extract_serial(serial_el.get_text(" ", strip=True) if serial_el else row.get_text(" ", strip=True))
                if not serial:
                    continue

                customer_name = _customer_from_row(row, serial)
                if customer_name and serial not in data_map:
                    data_map[serial] = customer_name
                                
        except Exception:
            logger.debug("BeautifulSoup customer map parsing failed", exc_info=True)

    return data_map

# ─────────────────────────────────────────────────────────────
# Public API used by http_client.SessionPool callers
# ─────────────────────────────────────────────────────────────
def _fetch_device_index_html(session: requests.Session, url: str) -> str:
    r = session.get(url, headers=HEADERS_COMMON, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text

def get_active_serials(session: requests.Session) -> List[str]:
    """
    Fetch the Toshiba eService device index using a **logged-in** session and
    return all device serials found on that page.

    - Assumes `session` is already authenticated (login handled elsewhere).
    - Mirrors the exact request old_http_client.py used:
        GET https://eservice.toshiba-solutions.com/Device/Index
        with the same HEADERS_COMMON.
    """
    return parse_serial_numbers(_fetch_device_index_html(session, DEVICE_INDEX))

def get_inactive_serials(session: requests.Session) -> List[str]:
    """
    Fetch the Toshiba eService device index using a **logged-in** session and
    return all inactive device serials found on that page.

    - Assumes `session` is already authenticated (login handled elsewhere).
    - Mirrors the exact request old_http_client.py used:
        GET https://eservice.toshiba-solutions.com/Device?tabIndex=1
        with the same HEADERS_COMMON.
    """
    return parse_serial_numbers(_fetch_device_index_html(session, DEVICE_INDEX_INACTIVE))
