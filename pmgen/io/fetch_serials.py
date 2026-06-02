from __future__ import annotations

from typing import List, Iterable, Dict
import re
import requests

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

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
                val = (el.get("data-serial") or "").strip()
                if val and _SERIAL_RE.fullmatch(val):
                    found.append(val)

            # hrefs with ?serial=XYZ or ?deviceSerial=XYZ
            for a in soup.find_all("a", href=True):
                href = a["href"]
                for key in ("serial", "deviceSerial"):
                    m = re.search(rf"(?:\?|&){key}=([^&#]+)", href)
                    if m:
                        cand = m.group(1).strip()
                        cand = re.sub(r"%2f|%2F|%20", "", cand)
                        if _SERIAL_RE.fullmatch(cand):
                            found.append(cand)
        except Exception:
            # fall back to regex sweep
            pass

    # Regex sweep for stragglers (JSON-inlined, plain text tables, etc.)
    for m in _SERIAL_RE.finditer(html):
        found.append(m.group(0))

    return _dedupe_preserve_order(found)

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
            
            for serial_el in soup.select(".deviceSerialNumbers"):
                serial = serial_el.get_text(strip=True)
                
                if serial:
                    row = serial_el.find_parent("tr")
                    
                    if row:
                        cust_el = row.select_one(".deviceCustomers")
                        if cust_el:
                            customer_name = cust_el.get_text(strip=True)
                            
                            if serial not in data_map:
                                data_map[serial] = customer_name
                                
        except Exception as e:
            # Log error if needed, or pass
            pass

    return data_map

def parse_description_map(html: str) -> Dict[str, str]:
    """
    Parses HTML to create a mapping of { Serial_Number : Description }.
    """
    if not isinstance(html, str) or not html:
        return {}

    data_map: Dict[str, str] = {}

    if BeautifulSoup is not None:
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            for serial_el in soup.select(".deviceSerialNumbers"):
                serial = serial_el.get_text(strip=True)
                
                if serial:
                    row = serial_el.find_parent("tr")
                    
                    if row:
                        desc_el = row.select_one(".deviceDescription")
                        if desc_el:
                            description = desc_el.get_text(strip=True)
                            
                            if serial not in data_map:
                                data_map[serial] = description

        except Exception:
            pass

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
