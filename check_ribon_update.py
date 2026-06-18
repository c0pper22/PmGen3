#!/usr/bin/env python3
"""
RIBON Update Checker
====================
Checks whether RIBON.exe has an available data update by:
1. Reading the current data version from Ribon.accdb (T_RBN_SET_UP table)
2. Calling the same SOAP web service (checkVersion) that RIBON.exe uses
3. Comparing versions and reporting if an update is available

Usage:
    python check_ribon_update.py                          # uses default paths
    python check_ribon_update.py --db /path/to/Ribon.accdb
    python check_ribon_update.py --url https://custom-ws-url/service
    python check_ribon_update.py --json                   # machine-readable output
"""

import argparse
import sys
import os
import json
import subprocess
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Defaults (mirrored from RIBON.exe decompilation)
# ---------------------------------------------------------------------------
DEFAULT_ACCBD_PATH = "C:\\TTECCDRibon\\db\\Ribon.accdb"
DEFAULT_WS_URL = (
    "https://topview.toshibatec.com/webribon/websw/"
    "CdribonAutoImportSoapHttpPort"
)

# WSDL-determined namespaces (from the live WSDL at the Toshiba Tec endpoint)
_TNS = "http://webservicecdribon.rbn.eqs.toshibatec.co.jp/"
_TNS0 = "http://webservicecdribon.rbn.eqs.toshibatec.co.jp/types/"

# SOAP envelope for the checkVersion call.
# The WSDL has elementFormDefault="qualified", so the wrapper and every
# parameter must be in the types namespace. Using a default namespace on the
# wrapper mirrors the .NET SoapHttpClientProtocol serialization.
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

# WSDL says: soapAction="http://webservicecdribon.rbn.eqs.toshibatec.co.jp//checkVersion"
# (note the double slash before the method name)
SOAP_ACTION = (
    "http://webservicecdribon.rbn.eqs.toshibatec.co.jp//checkVersion"
)


# ---------------------------------------------------------------------------
# Hardcoded database password from RIBON.exe (COS_CONNECTION constant)
# Found via ILSpy decompilation:
#   "Provider=microsoft.ace.oledb.12.0;Data Source={0} ; Persist Security
#    Info=true;User ID=Admin;Jet OLEDB:Database Password=rbn-MTomy3s8NuM7IbtQ"
# ---------------------------------------------------------------------------
DB_PASSWORD = "rbn-MTomy3s8NuM7IbtQ"


# ---------------------------------------------------------------------------
# Database helpers (Access .accdb via pyodbc + mdbtools or pypyodbc)
# ---------------------------------------------------------------------------
def get_access_connection(db_path: str):
    """
    Return a pyodbc connection to the Access database.
    Uses the hardcoded database password from RIBON.exe.

    On Linux, mdbtools with unixODBC works; on Windows, ACE.OLEDB is standard.
    """
    import importlib

    # Try pyodbc first, fall back to pypyodbc
    db_module = None
    for mod_name in ("pyodbc", "pypyodbc"):
        try:
            db_module = importlib.import_module(mod_name)
            break
        except ImportError:
            pass

    if db_module is None:
        raise ImportError(
            "Neither pyodbc nor pypyodbc is installed. "
            "Install with: pip install pyodbc"
        )

    last_err = None

    # List of ODBC connection strings to try in order.
    # pyodbc/pypyodbc only work with ODBC drivers, not OLEDB providers.
    connection_templates = [
        # 64-bit Access Driver (Windows)
        (
            "DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};"
            "DBQ={db};PWD={pwd};"
        ),
        # 32-bit Access Driver (Windows)
        (
            "DRIVER={{Microsoft Access Driver (*.mdb)}};"
            "DBQ={db};PWD={pwd};"
        ),
        # Linux via mdbtools (no password support)
        ("DRIVER={{MDBTools}};DBQ={db};"),
    ]

    for template in connection_templates:
        try:
            conn_str = template.format(db=db_path, pwd=DB_PASSWORD)
            conn = db_module.connect(conn_str)
            return conn
        except Exception as exc:
            last_err = exc
            continue

    raise RuntimeError(
        f"Could not open {db_path}. Last error: {last_err}\n"
        "On Linux, install mdbtools + unixODBC:\n"
        "  sudo apt install mdbtools unixodbc libmdbodbc\n"
        "On Windows, install Access Database Engine from Microsoft."
    )


def read_setup_info(db_path: str) -> dict:
    """
    Read the T_RBN_SET_UP row (SET_UP_ID = 0) from Ribon.accdb.
    Returns a dict with the relevant fields.
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = get_access_connection(db_path)
    cursor = conn.cursor()

    try:
        # Read the setup row
        cursor.execute("SELECT * FROM T_RBN_SET_UP WHERE SET_UP_ID = 0")
        row = cursor.fetchone()
        if row is None:
            # Try without WHERE, some databases have different IDs
            cursor.execute("SELECT * FROM T_RBN_SET_UP")
            row = cursor.fetchone()

        if row is None:
            raise ValueError(
                "T_RBN_SET_UP table is empty — does the database have data?"
            )

        # Build a dict from cursor.description
        columns = [desc[0] for desc in cursor.description]
        info = dict(zip(columns, row))

        # Helper: return None for NULL/None values, otherwise the string value.
        # This is important because .NET sends xsi:nil="true" for null strings,
        # and the server may differentiate between null and empty string.
        def _val(key, default=None):
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
            "access_control_grp": _val("ACCESS_CONTROL_GRP", ""),
        }
    finally:
        cursor.close()
        conn.close()


def read_setup_info_isolated(db_path: str) -> dict:
    """
    Read setup info in a child process.

    The Windows Access ODBC driver can crash at interpreter shutdown when the
    same process also performs HTTPS requests. Keeping the DB read isolated
    avoids that native-driver interaction.
    """
    if os.environ.get("RIBON_DIRECT_DB_READ") == "1":
        return read_setup_info(db_path)

    env = os.environ.copy()
    env["RIBON_DIRECT_DB_READ"] = "1"
    completed = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--dump-setup-info", db_path],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.stdout.strip():
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            pass

    message = (completed.stderr or completed.stdout or "unknown error").strip()
    raise RuntimeError(f"Database helper failed: {message}")


# ---------------------------------------------------------------------------
# SOAP web service client
# ---------------------------------------------------------------------------
def call_check_version(
    key_version: int,
    data_sub_version: int,
    bsi_flg: str,
    country_type: str,
    install_key: str,
    ws_url: str = DEFAULT_WS_URL,
    timeout: int = 30,
    debug: bool = False,
) -> dict:
    """
    Call the CdribonAutoImport.checkVersion SOAP method.
    Returns the parsed response as a dict:
      {
        "flag": str,           # "1" = success, "0" = error
        "file_name": str,      # download file name
        "size": str,           # file size (bytes?)
        "new_sub_version": str,# new data sub-version
        "new_main_version": str# new main data version
      }
    """
    import requests

    # Convert country_type: "0" -> "JPN", everything else -> "OVS"
    # (as seen in getContryType())
    country = "JPN" if str(country_type) == "0" else "OVS"

    # Build nillable string elements to match .NET SoapHttpClientProtocol behaviour:
    # empty/null strings are serialized with xsi:nil="true"
    def _str_el(tag, value):
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

    if debug:
        print("=== DEBUG: SOAP Request ===", file=sys.stderr)
        print(f"URL: {ws_url}", file=sys.stderr)
        print(f"Headers: {headers}", file=sys.stderr)
        print(f"Body:\n{soap_body}", file=sys.stderr)
        print("=== END DEBUG ===", file=sys.stderr)

    response = requests.post(
        ws_url,
        data=soap_body.encode("utf-8"),
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()

    if debug:
        print("=== DEBUG: SOAP Response ===", file=sys.stderr)
        print(f"Status: {response.status_code}", file=sys.stderr)
        print(f"Body:\n{response.text}", file=sys.stderr)
        print("=== END DEBUG ===", file=sys.stderr)

    return _parse_check_version_response(response.text)


def _parse_check_version_response(xml_text: str) -> dict:
    """
    Parse the SOAP XML response from checkVersion.

    Response wraps <result> elements (string, nillable, unbounded) inside
    <tns0:checkVersionResponseElement> in the SOAP body.
    """
    ns = {
        "soap": "http://schemas.xmlsoap.org/soap/envelope/",
        "tns0": _TNS0,
    }

    root = ET.fromstring(xml_text)

    # Find the wrapper element first
    wrapper = root.find(".//tns0:checkVersionResponseElement", ns)
    if wrapper is None:
        # Fallback: try without namespace prefix
        wrapper = root.find(".//{http://www.w3.org/2003/05/soap-envelope}Body")
        if wrapper is not None:
            wrapper = wrapper[0]  # first child of Body

    if wrapper is None:
        raise ValueError(
            "Could not find checkVersionResponseElement in SOAP response:\n"
            + xml_text[:1000]
        )

    # Collect all <result> children
    strings = []
    for child in wrapper:
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "result":
            strings.append((child.text or "").strip())

    # Pad to at least 5 elements (as expected by RIBON.exe logic)
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
def parse_version(version_str: str) -> tuple:
    """
    Parse CURRENT_DATA_VERSION (format "major.minor" or "major,minor")
    into (major, minor) integers.
    """
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
# Main update checking logic
# ---------------------------------------------------------------------------
def check_for_update(
    db_path: str = DEFAULT_ACCBD_PATH,
    ws_url: str = DEFAULT_WS_URL,
    timeout: int = 30,
    debug: bool = False,
) -> dict:
    """
    Main entry point: check if RIBON has an available update.

    Returns a dict with full details suitable for both human and
    machine consumption.
    """
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "database": os.path.abspath(db_path),
        "database_found": False,
        "web_service_url": ws_url,
        "web_service_reachable": False,
        "update_available": False,
        "error": None,
        # Local info from DB
        "local": {
            "data_version": None,
            "soft_version": None,
            "key_version": None,
            "data_sub_version": None,
        },
        # Remote info from WS
        "remote": {
            "flag": None,
            "file_name": None,
            "size": None,
            "new_sub_version": None,
            "new_main_version": None,
        },
    }

    # --- Step 1: Read local version from database ---
    try:
        info = read_setup_info_isolated(db_path)
        result["database_found"] = True
        result["local"]["data_version"] = info["current_data_version"]
        result["local"]["soft_version"] = info["current_soft_version"]

        key_ver, sub_ver = parse_version(info["current_data_version"])
        result["local"]["key_version"] = key_ver
        result["local"]["data_sub_version"] = sub_ver
    except FileNotFoundError as exc:
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["error"] = f"Database read error: {exc}"
        return result

    # --- Step 2: Call the web service ---
    import requests

    try:
        remote = call_check_version(
            key_version=key_ver,
            data_sub_version=sub_ver,
            bsi_flg=info["bsi_flg"],
            country_type=info["country_type"],
            install_key=info["current_install_key"],
            ws_url=ws_url,
            timeout=timeout,
            debug=debug,
        )
        result["web_service_reachable"] = True
        result["remote"] = remote
    except requests.exceptions.ConnectionError as exc:
        result["error"] = (
            f"Cannot reach web service at {ws_url}: {exc}"
        )
        return result
    except requests.exceptions.Timeout as exc:
        result["error"] = f"Web service timed out after {timeout}s"
        return result
    except Exception as exc:
        result["error"] = f"Web service error: {exc}"
        return result

    # --- Step 3: Compare versions ---
    remote_data = result["remote"]

    # flag "0" means error from the service
    if remote_data["flag"] == "0":
        result["error"] = (
            "Web service returned error (flag=0). "
            "The install key or other parameters may be incorrect."
        )
        return result

    # If new_sub_version is "0" and new_main_version == current, no update
    current_version_str = result["local"]["data_version"]
    new_sub = remote_data["new_sub_version"]
    new_main = remote_data["new_main_version"]

    if new_sub == "0" and new_main == current_version_str:
        # No new data available
        result["update_available"] = False
        return result

    # new_sub_version == "0" but new_main differs → new major version
    if new_sub == "0" and new_main != current_version_str:
        result["update_available"] = True
        result["update_type"] = "major_version_change"
        return result

    # new_sub_version != "0" → there is an incremental update
    try:
        remote_sub = int(new_sub)
        if remote_sub > sub_ver:
            result["update_available"] = True
            result["update_type"] = "incremental_update"
        else:
            result["update_available"] = False
    except ValueError:
        result["error"] = (
            f"Unparseable new sub version from server: {new_sub!r}"
        )

    return result


# ---------------------------------------------------------------------------
# CLI output formatters
# ---------------------------------------------------------------------------
def print_human(result: dict) -> None:
    """Print a human-readable summary."""
    local = result["local"]
    remote = result["remote"]

    print("=" * 60)
    print("  RIBON Update Checker")
    print("=" * 60)
    print(f"  Checked at : {result['checked_at']}")
    print(f"  Database   : {result['database']}")
    print(f"  DB found   : {result['database_found']}")
    print(f"  WS URL     : {result['web_service_url']}")
    print(f"  WS reachable: {result['web_service_reachable']}")
    print("-" * 60)

    if result["error"]:
        print(f"  ERROR      : {result['error']}")
        print("=" * 60)
        sys.exit(1)

    print(f"  Local  data version : {local['data_version']}")
    print(f"  Local  soft version : {local['soft_version']}")
    print(f"  Remote new main ver : {remote['new_main_version']}")
    print(f"  Remote new sub  ver : {remote['new_sub_version']}")
    print(f"  Remote file name    : {remote['file_name']}")
    print(f"  Remote file size    : {remote['size']}")
    print("-" * 60)

    if result["update_available"]:
        update_type = result.get("update_type", "unknown")
        print(f"  ✅ UPDATE AVAILABLE ({update_type})")
        if update_type == "major_version_change":
            print(f"     New major version: {remote['new_main_version']}")
        else:
            new_sub = remote["new_sub_version"]
            key = local["key_version"]
            print(
                f"     Available: {key}.{local['data_sub_version']} "
                f"→ {key}.{new_sub}"
            )
    else:
        print("  ✅ No update available (up to date)")

    print("=" * 60)


def print_json(result: dict) -> None:
    """Print JSON machine-readable output."""
    print(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Check if RIBON.exe has an available data update.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_ribon_update.py
  python check_ribon_update.py --db "C:\\RIBON\\Ribon.accdb"
  python check_ribon_update.py --url https://custom-ws/service.asmx
  python check_ribon_update.py --json
        """,
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_ACCBD_PATH,
        help=f"Path to Ribon.accdb (default: {DEFAULT_ACCBD_PATH})",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_WS_URL,
        help="Web service URL (default: built-in Toshiba Tec URL)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Web service timeout in seconds (default: 30)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output in JSON format (machine-readable)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print raw SOAP request/response to stderr for troubleshooting",
    )
    parser.add_argument(
        "--dump-setup-info",
        metavar="DB_PATH",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    if args.dump_setup_info:
        print_json(read_setup_info(args.dump_setup_info))
        sys.exit(0)

    result = check_for_update(
        db_path=args.db,
        ws_url=args.url,
        timeout=args.timeout,
        debug=args.debug,
    )

    if args.json:
        print_json(result)
    else:
        print_human(result)

    # Exit code: 0 = up to date, 1 = update available, 2 = error
    if result["error"]:
        sys.exit(2)
    if result["update_available"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()