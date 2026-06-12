from __future__ import annotations

import os
import sys
from PyQt6.QtCore import QStandardPaths
import re
import logging
from contextlib import contextmanager
from queue import LifoQueue, Empty
from typing import Optional, List, Dict, Callable
from datetime import date

import requests
from weakref import WeakSet

from pmgen.io.fetch_serials import parse_serial_numbers, parse_customer_map

# from pmgen.ui.main_window import SERVICE_NAME # Circular import risk, handled below
SERVICE_NAME = "PmGen"

# Logging (safe; excludes credentials)
LOG_DIR = os.path.join(os.path.expanduser("~"), ".indybiz_pm")
os.makedirs(LOG_DIR, exist_ok=True)
log = logging.getLogger("IndyBizPM.HTTP")

# HTTP constants
BASE_URL = "https://eservice.toshiba-solutions.com"
LOGIN_PAGE = f"{BASE_URL}/Account/LogOn"
LOGIN_POST = f"{BASE_URL}/Account/LogOn"
SERVICE_FILES = f"{BASE_URL}/Device/GetServiceFiles"
DEVICE_INDEX = f"{BASE_URL}/Device/Index"
DEVICE_INDEX_INACTIVE = f"{BASE_URL}/Device?tabIndex=1"
LOGOUT_URL = f"{BASE_URL}/Account/LogOff"

HEADERS_COMMON = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) "
                   "Gecko/20100101 Firefox/128.0"),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": LOGIN_PAGE,
}

# --- Keyring-backed credentials (same behavior as before) ---
try:
    import keyring  # type: ignore
except Exception:  # pragma: no cover
    keyring = None

def get_db_path():
    """
    Returns runtime database path.
    - Source/Python runs: use current working directory.
    - Frozen/compiled runs: use AppData location.
    """
    if not getattr(sys, "frozen", False):
        return os.path.join(os.getcwd(), "catalog_manager.db")

    app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    if not os.path.exists(app_data):
        os.makedirs(app_data)
    return os.path.join(app_data, "catalog_manager.db")

def get_saved_username() -> Optional[str]:
    if not keyring:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, "username")
    except Exception:
        return None

def get_saved_password() -> Optional[str]:
    if not keyring:
        return None
    try:
        u = get_saved_username()
        if not u:
            return None
        return keyring.get_password(SERVICE_NAME, u)
    except Exception:
        return None

def save_credentials(username: str, password: str) -> None:
    if not keyring:
        raise RuntimeError("Install 'keyring' with: pip install keyring")
    if not username or not password:
        raise ValueError("Username and Password cannot be empty.")
    keyring.set_password(SERVICE_NAME, "username", username)
    keyring.set_password(SERVICE_NAME, username, password)

def clear_credentials() -> None:
    """Delete the 'username' marker and its password under the unified service."""
    if not keyring:
        return
    try:
        u = keyring.get_password(SERVICE_NAME, "username")
    except Exception:
        u = None
    try:
        keyring.delete_password(SERVICE_NAME, "username")
    except Exception:
        pass
    if u:
        try:
            keyring.delete_password(SERVICE_NAME, u)
        except Exception:
            pass

# --- Login helpers (unchanged behavior) ---

def _extract_anti_forgery(html: str) -> str:
    m = re.search(r'name="__RequestVerificationToken"\s+type="hidden"\s+value="([^"]+)"', html)
    if not m:
        raise RuntimeError("Could not find __RequestVerificationToken on login page.")
    return m.group(1)

def login(sess: requests.Session) -> None:
    """
    Logs in the provided session using saved credentials.
    Raises on failure.
    """
    username = get_saved_username()
    password = get_saved_password()

    log.info(f"Attempting login flow for user: {username}")

    try:
        r = sess.get(LOGIN_PAGE, headers=HEADERS_COMMON, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Failed to reach login page: {e}")
        raise

    if not (username and password):
        raise RuntimeError("No saved credentials. Use Settings -> Credentials...")

    log.info("Fetching login page for token.")
    r = sess.get(LOGIN_PAGE, headers=HEADERS_COMMON, timeout=30)
    r.raise_for_status()
    token = _extract_anti_forgery(r.text)

    form = {
        "UserName": username,
        "Password": password,
        "OneTimePassword": "",
        "RememberMe2FA": "false",
        "timeZoneOffSet": "0",
        "returnUrl": "/Device/Index",
        "serial": "",
        "__RequestVerificationToken": token,
    }

    headers = {
        **HEADERS_COMMON,
        "Origin": BASE_URL,
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    }

    try:
        r = sess.post(LOGIN_POST, data=form, headers=headers, timeout=30)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Login POST failed: {e}")
        raise

    if r.headers.get("Content-Type", "").lower().startswith("application/json"):
        try:
            js = r.json()
            page_value = js.get("page", "")
            if "Invalid User Name or Password" in page_value:
                raise RuntimeError("Login failed: Invalid User Name or Password.")
        except ValueError:
            log.warning("Response Content-Type was JSON but could not parse body.")

    chk = sess.get(DEVICE_INDEX, headers=HEADERS_COMMON, timeout=30, allow_redirects=True)

    if "Log On" in chk.text or chk.status_code in (401, 403):
        raise RuntimeError("Login appears unsuccessful (got login page again).")

    log.info("Login successful.")

# --- Session Pool (thread-safe) ---
class SessionPool:
    """
    Thread-safe pool of logged-in requests.Session objects.
    Use: with pool.acquire() as sess: ...
    """
    _all_pools: WeakSet = WeakSet()

    def __init__(self, size: int, callback: Optional[Callable[[int, int], None]] = None):
        """
        Initialize the pool.
        :param size: Number of sessions to create.
        :param callback: Optional function(current, total) called after each login.
        """
        size = max(1, int(size))
        self._q: LifoQueue[requests.Session] = LifoQueue()
        
        for i in range(size):
            try:
                s = requests.Session()
                login(s)
                self._q.put(s)
                
                # Notify progress if a callback is provided
                if callback:
                    callback(i + 1, size)
            except Exception as e:
                log.error(f"Failed to initialize session {i+1}/{size}: {e}")
                # We continue even if one fails, though typically login() raises.
                # If all fail, the pool might be empty or partially filled.

        self._size = size
        
        # register this pool so we can close on logout
        try:
            SessionPool._all_pools.add(self)
        except Exception:
            pass
        log.info(f"SessionPool initialized with {self._q.qsize()} logged-in session(s).")

    @contextmanager
    def acquire(self):
        sess = None
        try:
            sess = self._q.get(timeout=60)
            yield sess
        finally:
            if sess is not None:
                try:
                    self._q.put(sess)
                except Exception:
                    pass

    def close(self) -> None:
        n = 0
        while True:
            try:
                s = self._q.get_nowait()
            except Empty:
                break
            try:
                s.close()
            except Exception:
                pass
            n += 1
        log.info(f"SessionPool closed {n} session(s).")

    @classmethod
    def close_all_pools(cls) -> int:
        """Close all known pools; returns number of pools closed."""
        n = 0
        dead = []
        for p in list(cls._all_pools):
            try:
                p.close()
                n += 1
            except Exception:
                pass
            finally:
                dead.append(p)
        for p in dead:
            try:
                cls._all_pools.discard(p)
            except Exception:
                pass
        return n

# --- Reusable HTTP helpers that accept an optional session ---
def get_service_file_bytes(serial: str, option: str = "PMSupport",
                           sess: Optional[requests.Session] = None) -> bytes:
    """
    Download a service file for the given serial and option.
    If *sess* is None, a temp session is created and closed (same behavior as before).
    """
    owns_session = False
    if sess is None:
        sess = requests.Session()
        login(sess)
        owns_session = True
    try:
        params = {"deviceSerial": serial, "option": option}
        headers = {**HEADERS_COMMON, "Referer": DEVICE_INDEX}
        log.info(f"Requesting service file: serial={serial}, option={option}")
        r = sess.get(SERVICE_FILES, params=params, headers=headers, timeout=60, stream=True)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            raise RuntimeError("Expected file bytes; got HTML (likely not logged in).")
        return r.content
    finally:
        if owns_session:
            try:
                sess.close()
            except Exception:
                pass

def _fetch_device_index_html(sess: requests.Session, url: str) -> str:
    r = sess.get(url, headers=HEADERS_COMMON, timeout=30, allow_redirects=True)
    r.raise_for_status()
    return r.text

def _device_index_pages(sess: requests.Session) -> List[str]:
    return [
        _fetch_device_index_html(sess, DEVICE_INDEX),
        _fetch_device_index_html(sess, DEVICE_INDEX_INACTIVE),
    ]

def get_serial_status_map_after_login(sess: requests.Session) -> Dict[str, str]:
    """
    Return a {serial: machine_status} map for active and inactive device tabs.
    Active wins if the same serial appears on both tabs.
    """
    serial_status_map: Dict[str, str] = {}
    for machine_status, url in (("Active", DEVICE_INDEX), ("Inactive", DEVICE_INDEX_INACTIVE)):
        html = _fetch_device_index_html(sess, url)
        for serial in parse_serial_numbers(html):
            serial_status_map.setdefault(serial, machine_status)
    return serial_status_map

def get_serials_after_login(sess: requests.Session) -> List[str]:
    """
    Navigate to active and inactive Device Index pages and parse serials.
    Requires a logged-in session.
    """
    return list(get_serial_status_map_after_login(sess).keys())

def get_customer_map_after_login(sess: requests.Session) -> Dict[str, str]:
    customer_map: Dict[str, str] = {}
    for html in _device_index_pages(sess):
        for serial, customer_name in parse_customer_map(html).items():
            customer_map.setdefault(serial, customer_name)
    return customer_map

def _parse_unpacking_date_from_08_bytes(blob: bytes) -> Optional[date]:
    """
    Look for the 08 Setting Mode "Unpacking date" (code 3612).
    Handles packed numeric format like:
        3612, , 2507292085501,
    where first 6 digits are YYMMDD.
    """
    for raw in blob.decode(errors="ignore").splitlines():
        if "3612" not in raw:
            continue
        # find a long numeric token after 3612
        parts = re.split(r"[,\s]+", raw.strip())
        try:
            idx = parts.index("3612")
        except ValueError:
            continue

        # search forward for the first 6+ digit number
        for token in parts[idx + 1:]:
            if re.fullmatch(r"\d{6,}", token):
                try:
                    yy = int(token[0:2])
                    mm = int(token[2:4])
                    dd = int(token[4:6])
                    year = 2000 + yy  # assume 20xx
                    return date(year, mm, dd)
                except Exception:
                    break
    return None

def get_unpacking_date(serial: str, sess: Optional[requests.Session] = None) -> Optional[date]:
    """
    Fetch the 08 Setting Mode file for *serial* and return the unpacking date (CODE=3612)
    as a datetime.date, or None if not present/parseable.
    """
    try:
        blob = get_service_file_bytes(serial, option="08", sess=sess)
    except Exception:
        return None
    return _parse_unpacking_date_from_08_bytes(blob)

def _parse_model_from_08_bytes(blob: bytes) -> str:
    """
    Look for the 08 Setting Mode "Model Name" (code 9486).
    Example line: 9486, , TOSHIBA e-STUDIO5525AC,
    """
    try:
        text = blob.decode(errors="ignore")
        for line in text.splitlines():
            if "9486" in line:
                parts = [p.strip() for p in line.split(",")]
                if "9486" in parts:
                    idx = parts.index("9486")
                    for candidate in parts[idx+1:]:
                        if candidate:
                            return candidate
    except Exception:
        pass
    return "Unknown"


def _parse_code_from_csv_bytes(code: int, sub: int, blob: bytes) -> str:
    """
    Parses a 08/05 CSV blob and returns the DATA value for the given code and sub.

    Expected CSV format:
        CODE, SUB, DATA,
        2405, 0, 6199,
        2405, 1, 6184,

    Args:
        code (int): The code to search for.
        sub (int): The sub-code to filter by. Matches rows where the SUB column
                   equals this value (0 matches subcode 0 or empty sub).
                   Use -1 to match any sub.
        blob (bytes): The byte content of the CSV file.
    Returns:
        str: The DATA column value, joined by commas if multiple data columns.
             Returns empty string if not found.
    """
    try:
        text = blob.decode('utf-8')
    except UnicodeDecodeError:
        text = blob.decode('latin-1', errors='replace')

    lines = text.splitlines()
    target_code_str = str(code)
    target_sub_str = str(sub)
    start_processing = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("CODE,"):
            start_processing = True
            continue

        if not start_processing:
            continue

        parts = line.split(',')
        if len(parts) < 3:
            continue

        current_code = parts[0].strip()
        current_sub = parts[1].strip()

        if current_code != target_code_str:
            continue

        # sub=-1: match any sub (backward compat). sub=0: match literal "0" OR empty sub.
        sub_matches = (
            sub == -1
            or current_sub == target_sub_str
            or (sub == 0 and current_sub == "")
        )
        if sub_matches:
            data_parts = parts[2:-1] if parts[-1].strip() == '' else parts[2:]
            return ",".join(p.strip() for p in data_parts if p.strip())

    return ""


def _parse_code_from_08_bytes(code: int, blob: bytes) -> str:
    """Backward-compatible wrapper — matches first occurrence of code regardless of sub."""
    return _parse_code_from_csv_bytes(code, -1, blob)

def get_device_info_08(serial: str, sess: Optional[requests.Session] = None) -> Dict:
    """
    Fetch the 08 Setting Mode file and return both Date and Model.
    Returns: {'date': datetime.date | None, 'model': str}
    """


    try:
        blob = get_service_file_bytes(serial, option="08", sess=sess)
        return {
            "date": _parse_unpacking_date_from_08_bytes(blob),
            "model": _parse_model_from_08_bytes(blob),
        }
    except Exception:
        return {"date": None, "model": "Unknown"}

def server_side_logout(sess: Optional[requests.Session] = None) -> None:
    """Best-effort: call portal logout endpoint with a session (or temp one)."""
    s = sess or requests.Session()
    try:
        s.get(LOGOUT_URL, headers=HEADERS_COMMON, timeout=10, allow_redirects=True)
    except Exception:
        pass