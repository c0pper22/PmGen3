"""
RIBON database update checker
==============================
Checks whether the RIBON.exe data (Ribon.accdb) has an available update by:
1. Reading the current data version from T_RBN_SET_UP
2. Calling the SOAP web service (checkVersion) that RIBON.exe itself uses
3. Comparing versions and reporting whether an update is available

The check runs on a background QThread and emits a signal with the result.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reuse DB configuration from ribon_db (same Access database, same password)
# ---------------------------------------------------------------------------
from pmgen.io.ribon_db import RIBON_DB_PATH, RIBON_DB_PASSWORD  # noqa: E402

# Defaults mirrored from RIBON.exe decompilation
DEFAULT_WS_URL = (
    "https://topview.toshibatec.com/webribon/websw/"
    "CdribonAutoImportSoapHttpPort"
)
SOAP_ACTION = (
    "http://webservicecdribon.rbn.eqs.toshibatec.co.jp//checkVersion"
)

# WSDL namespaces
_TNS0 = "http://webservicecdribon.rbn.eqs.toshibatec.co.jp/types/"

# ---------------------------------------------------------------------------
# SOAP envelope template
# ---------------------------------------------------------------------------
SOAP_ENVELOPE_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope
    xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <soap:Body>
    <checkVersionElement xmlns="http://webservicecdribon.rbn.eqs.toshibatec.co.jp/types/">
      <int_1>{key_version}</int_1>
      <int_2>{data_sub_version}</int_2>
      {int_3_el}
      {string_4_el}
      {string_5_el}
    </checkVersionElement>
  </soap:Body>
</soap:Envelope>"""


# ---------------------------------------------------------------------------
# Read T_RBN_SET_UP — runs in a child process to avoid ODBC + HTTPS crash
# ---------------------------------------------------------------------------

def _read_setup_info(db_path: str) -> dict[str, str | None]:
    """Read T_RBN_SET_UP (SET_UP_ID=0) directly from the Access database.

    Returns a dict with keys: current_data_version, current_soft_version,
    current_install_key, bsi_flg, country_type.
    """
    import pyodbc as _pyodbc

    conn_str = (
        r"Driver={Microsoft Access Driver (*.mdb, *.accdb)};"
        f"DBQ={db_path};PWD={RIBON_DB_PASSWORD};"
    )

    with _pyodbc.connect(conn_str, autocommit=True) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM T_RBN_SET_UP WHERE SET_UP_ID = 0")
            row = cursor.fetchone()
            if row is None:
                cursor.execute("SELECT * FROM T_RBN_SET_UP")
                row = cursor.fetchone()
            if row is None:
                raise ValueError(
                    "T_RBN_SET_UP table is empty — does the database have data?"
                )

            columns = [desc[0] for desc in cursor.description]
            info = dict(zip(columns, row))

            def _val(key: str, default: str | None = None) -> str | None:
                v = info.get(key)
                if v is None:
                    return default
                s = str(v).strip()
                return s if s else default

            return {
                "current_data_version": _val("CURRENT_DATA_VERSION", ""),
                "current_soft_version": _val("CURRENT_SOFT_VERSION", ""),
                "current_install_key": _val("CURRENT_INSTALL_KEY", None),
                "bsi_flg": _val("BSI_FLG", "1"),
                "country_type": _val("COUNTRY_TYPE", "0"),
            }
        finally:
            cursor.close()


def _read_setup_info_isolated(db_path: str) -> dict[str, str | None]:
    """Run _read_setup_info in a child process.

    The Windows Access ODBC driver can crash at interpreter shutdown when
    the same process also performs HTTPS requests. Isolating the DB read
    avoids that native-driver interaction.
    """
    import json as _json
    import os as _os

    if _os.environ.get("RIBON_DIRECT_DB_READ") == "1":
        # Already inside the child process
        result = _read_setup_info(db_path)
        print(_json.dumps(result))
        return result

    env = _os.environ.copy()
    env["RIBON_DIRECT_DB_READ"] = "1"

    proj_root = _os.path.dirname(
        _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    )

    # Build a small inline helper script
    helper_code = (
        "import json, os, sys; "
        "os.environ['RIBON_DIRECT_DB_READ'] = '1'; "
        f"sys.path.insert(0, {proj_root!r}); "
        "from pmgen.io.ribon_update_check import _read_setup_info; "
        f"result = _read_setup_info({db_path!r}); "
        "print(json.dumps(result))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", helper_code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.stdout.strip():
        try:
            return _json.loads(completed.stdout)
        except _json.JSONDecodeError:
            pass

    message = (completed.stderr or completed.stdout or "unknown error").strip()
    raise RuntimeError(f"RIBON DB helper failed: {message}")


# ---------------------------------------------------------------------------
# SOAP client
# ---------------------------------------------------------------------------

def _call_check_version(
    key_version: int,
    data_sub_version: int,
    bsi_flg: str,
    country_type: str,
    install_key: str | None,
    ws_url: str = DEFAULT_WS_URL,
    timeout: int = 15,
) -> dict[str, str]:
    """Call CdribonAutoImport.checkVersion and return the parsed response.

    Returns dict with keys: flag, file_name, size, new_sub_version, new_main_version.
    """
    import requests

    country = "JPN" if str(country_type) == "0" else "OVS"

    def _str_el(tag: str, value: str | None) -> str:
        if value is None or str(value).strip() == "":
            return f'<{tag} xsi:nil="true"/>'
        return f"<{tag}>{value}</{tag}>"

    soap_body = SOAP_ENVELOPE_TEMPLATE.format(
        key_version=key_version,
        data_sub_version=data_sub_version,
        int_3_el=_str_el("int_3", bsi_flg),
        string_4_el=_str_el("String_4", country),
        string_5_el=_str_el("String_5", install_key),
    )

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTION,
    }

    response = requests.post(
        ws_url,
        data=soap_body.encode("utf-8"),
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    return _parse_check_version_response(response.text)


def _parse_check_version_response(xml_text: str) -> dict[str, str]:
    """Parse the SOAP XML response and extract result elements."""
    from xml.etree import ElementTree as ET

    ns = {
        "soap": "http://schemas.xmlsoap.org/soap/envelope/",
        "tns0": _TNS0,
    }

    root = ET.fromstring(xml_text)

    # Try namespace-qualified lookup first
    wrapper = root.find(".//tns0:checkVersionResponseElement", ns)
    if wrapper is None:
        # Fallback: first child of SOAP body
        body = root.find(".//{http://www.w3.org/2003/05/soap-envelope}Body")
        if body is not None and len(body) > 0:
            wrapper = body[0]

    if wrapper is None:
        raise ValueError(
            "Could not find checkVersionResponseElement in SOAP response"
        )

    strings: list[str] = []
    for child in wrapper:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "result":
            strings.append((child.text or "").strip())

    # Pad to at least 5 elements (as expected by RIBON.exe)
    while len(strings) < 5:
        strings.append("")

    return {
        "flag": strings[0],
        "file_name": strings[1],
        "size": strings[2],
        "new_sub_version": strings[3],
        "new_main_version": strings[4],
    }


# ---------------------------------------------------------------------------
# Version parsing
# ---------------------------------------------------------------------------

def _parse_version(version_str: str) -> tuple[int, int]:
    """Parse a version string like '3.5' or '3,5' into (major, minor)."""
    version_str = str(version_str).strip()
    if not version_str:
        return (0, 0)

    for sep in (".", ","):
        parts = version_str.split(sep)
        if len(parts) == 2:
            try:
                return (int(parts[0]), int(parts[1]))
            except ValueError:
                pass

    raise ValueError(f"Cannot parse version string: {version_str!r}")


# ---------------------------------------------------------------------------
# Core check logic (runs on background thread)
# ---------------------------------------------------------------------------

def run_ribon_check(db_path: str = RIBON_DB_PATH, timeout: int = 15) -> dict[str, Any]:
    """Perform a full RIBON update check synchronously.

    Returns a structured result dict suitable for the UI signal.
    """
    import requests as _requests

    result: dict[str, Any] = {
        "update_available": False,
        "error": None,
        "local_version": None,
        "remote_version": None,
    }

    # --- Step 1: Read local DB ---
    import os as _os

    if not _os.path.isfile(db_path):
        result["error"] = "db_not_found"
        logger.info("RIBON DB not found at %s; skipping update check.", db_path)
        return result

    try:
        info = _read_setup_info_isolated(db_path)
        key_ver, sub_ver = _parse_version(info["current_data_version"])
        result["local_version"] = f"{key_ver}.{sub_ver}"
        logger.info("Read RIBON local version: %s", result["local_version"])
    except FileNotFoundError:
        result["error"] = "db_not_found"
        logger.info("RIBON DB not found at %s; skipping update check.", db_path)
        return result
    except Exception as exc:
        result["error"] = f"db_read_error: {exc}"
        logger.warning("Failed to read RIBON setup info: %s", exc)
        return result

    # --- Step 2: Call web service ---
    try:
        remote = _call_check_version(
            key_version=key_ver,
            data_sub_version=sub_ver,
            bsi_flg=info["bsi_flg"],
            country_type=info["country_type"],
            install_key=info["current_install_key"],
            ws_url=DEFAULT_WS_URL,
            timeout=timeout,
        )
    except _requests.exceptions.ConnectionError as exc:
        result["error"] = f"ws_unreachable: {exc}"
        logger.info("RIBON web service unreachable; skipping update check.")
        return result
    except _requests.exceptions.Timeout as exc:
        result["error"] = f"ws_timeout: {exc}"
        logger.info("RIBON web service timed out after %ss; skipping update check.", timeout)
        return result
    except Exception as exc:
        result["error"] = f"ws_error: {exc}"
        logger.warning("RIBON web service error: %s", exc)
        return result

    # --- Step 3: Compare versions ---
    if remote["flag"] == "0":
        result["error"] = "ws_flag_zero"
        logger.info("RIBON check: web service returned flag=0 (install key may be incorrect)")
        return result

    new_sub = remote["new_sub_version"]
    new_main = remote["new_main_version"]

    if new_sub == "0" and new_main == info["current_data_version"]:
        # No update
        logger.info("RIBON database is up to date (version %s)", result["local_version"])
        return result

    # new_sub == "0" but new_main differs → major version change
    if new_sub == "0" and new_main != info["current_data_version"]:
        result["update_available"] = True
        result["update_type"] = "major"
        result["remote_version"] = new_main
        logger.info(
            "RIBON update available (major): %s → %s",
            result["local_version"],
            new_main,
        )
        return result

    # Incremental update if new_sub > local sub_version
    try:
        remote_sub = int(new_sub)
        if remote_sub > sub_ver:
            result["update_available"] = True
            result["update_type"] = "incremental"
            result["remote_version"] = f"{key_ver}.{remote_sub}"
            logger.info(
                "RIBON update available (incremental): %s → %s",
                result["local_version"],
                result["remote_version"],
            )
    except ValueError:
        result["error"] = f"unparseable_version: {new_sub!r}"

    return result


# ---------------------------------------------------------------------------
# QObject worker for background thread
# ---------------------------------------------------------------------------

class RibonCheckWorker(QObject):
    """Worker that checks RIBON DB freshness on a background QThread."""

    check_finished = pyqtSignal(bool, object)  # (update_available, result_dict)

    def __init__(self, db_path: str | None = None, timeout: int = 15, parent=None):
        super().__init__(parent)
        self._db_path = db_path or RIBON_DB_PATH
        self._timeout = timeout

    @pyqtSlot()
    def run_check(self) -> None:
        """Execute the check and emit check_finished."""
        try:
            result = run_ribon_check(db_path=self._db_path, timeout=self._timeout)
            self.check_finished.emit(result["update_available"], result)
        except Exception as exc:
            logger.exception("RIBON check worker crashed")
            self.check_finished.emit(
                False, {"update_available": False, "error": f"worker_crash: {exc}"}
            )
