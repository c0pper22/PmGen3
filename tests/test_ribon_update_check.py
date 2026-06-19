"""Tests for pmgen.io.ribon_update_check — pure functions and edge cases.

These tests exercise the testable surface without touching a real Access
database or the live Toshiba web service.  Integration paths that require
a real Ribon.accdb or network are excluded from the unit suite.
"""

from __future__ import annotations

import pytest

from pmgen.io.ribon_update_check import (
    _parse_version,
    _parse_check_version_response,
    run_ribon_check,
)

# ============================================================================
# _parse_version
# ============================================================================


@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("3.5", (3, 5)),
        ("3,5", (3, 5)),
        ("10.20", (10, 20)),
        ("0.0", (0, 0)),
        ("999.999", (999, 999)),
        ("1.0", (1, 0)),
        ("0.1", (0, 1)),
    ],
)
def test_parse_version_valid(input_str, expected):
    assert _parse_version(input_str) == expected


@pytest.mark.parametrize(
    "input_str",
    [
        "nonsense",
        "1.2.3",
        "1",
        "a.b",
        "1.2.3.4",
    ],
)
def test_parse_version_invalid_raises(input_str):
    with pytest.raises((ValueError, AttributeError)):
        _parse_version(input_str)


@pytest.mark.parametrize("input_str", ["", "   "])
def test_parse_version_empty_returns_zero(input_str):
    """Empty or whitespace-only version strings return (0, 0)."""
    assert _parse_version(input_str) == (0, 0)


# ============================================================================
# _parse_check_version_response
# ============================================================================

_VALID_SOAP_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/">
  <soapenv:Body>
    <tns0:checkVersionResponseElement
        xmlns:tns0="http://webservicecdribon.rbn.eqs.toshibatec.co.jp/types/">
      <result>1</result>
      <result></result>
      <result>12345</result>
      <result>8</result>
      <result>3.10</result>
    </tns0:checkVersionResponseElement>
  </soapenv:Body>
</soapenv:Envelope>"""


def test_parse_check_version_response_valid():
    parsed = _parse_check_version_response(_VALID_SOAP_RESPONSE)
    assert parsed["flag"] == "1"
    assert parsed["file_name"] == ""
    assert parsed["size"] == "12345"
    assert parsed["new_sub_version"] == "8"
    assert parsed["new_main_version"] == "3.10"


def test_parse_check_version_response_fewer_results_pads():
    xml = """<?xml version="1.0"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <tns0:checkVersionResponseElement
        xmlns:tns0="http://webservicecdribon.rbn.eqs.toshibatec.co.jp/types/">
      <result>1</result>
      <result>update.zip</result>
    </tns0:checkVersionResponseElement>
  </soap:Body>
</soap:Envelope>"""
    parsed = _parse_check_version_response(xml)
    assert parsed["flag"] == "1"
    assert parsed["file_name"] == "update.zip"
    assert parsed["size"] == ""
    assert parsed["new_sub_version"] == ""
    assert parsed["new_main_version"] == ""


def test_parse_check_version_response_fallback_body_child():
    """When the namespace-prefixed lookup fails, fall back to first child of Body."""
    xml = """<?xml version="1.0"?>
<env:Envelope xmlns:env="http://www.w3.org/2003/05/soap-envelope">
  <env:Body>
    <wrapper>
      <result>0</result>
      <result>file.dat</result>
      <result>0</result>
      <result>0</result>
      <result>4.2</result>
    </wrapper>
  </env:Body>
</env:Envelope>"""
    parsed = _parse_check_version_response(xml)
    assert parsed["flag"] == "0"
    assert parsed["new_main_version"] == "4.2"


def test_parse_check_version_response_no_wrapper_raises():
    xml = '<?xml version="1.0"?><root><x/></root>'
    with pytest.raises(ValueError):
        _parse_check_version_response(xml)


# ============================================================================
# run_ribon_check — happy and error paths (mocked IO)
# ============================================================================


class _FakeSetupInfoForCheck:
    """Simulate a successful DB read returning known setup info."""

    @staticmethod
    def __call__(db_path: str) -> dict[str, str | None]:
        return {
            "current_data_version": "3.5",
            "current_soft_version": "1.0",
            "current_install_key": "KEY123",
            "bsi_flg": "1",
            "country_type": "0",
        }


class _FakeCheckVersionNoUpdate:
    """Simulate a web service that says no update is available."""

    @staticmethod
    def __call__(
        key_version, data_sub_version,
        bsi_flg, country_type, install_key,
        ws_url, timeout,
    ) -> dict[str, str]:
        return {
            "flag": "1",
            "file_name": "",
            "size": "0",
            "new_sub_version": "0",
            "new_main_version": "3.5",
        }


class _FakeCheckVersionIncrementalUpdate:
    """Simulate a web service reporting an incremental sub-version update."""

    @staticmethod
    def __call__(
        key_version, data_sub_version,
        bsi_flg, country_type, install_key,
        ws_url, timeout,
    ) -> dict[str, str]:
        return {
            "flag": "1",
            "file_name": "update.zip",
            "size": "5000",
            "new_sub_version": "7",
            "new_main_version": "3.5",
        }


class _FakeCheckVersionMajorUpdate:
    """Simulate a major version bump."""

    @staticmethod
    def __call__(
        key_version, data_sub_version,
        bsi_flg, country_type, install_key,
        ws_url, timeout,
    ) -> dict[str, str]:
        return {
            "flag": "1",
            "file_name": "v4.zip",
            "size": "9999",
            "new_sub_version": "0",
            "new_main_version": "4.0",
        }


class _FakeCheckVersionFlagZero:
    """Simulate flag=0 (error) from the web service."""

    @staticmethod
    def __call__(
        key_version, data_sub_version,
        bsi_flg, country_type, install_key,
        ws_url, timeout,
    ) -> dict[str, str]:
        return {
            "flag": "0",
            "file_name": "",
            "size": "",
            "new_sub_version": "",
            "new_main_version": "",
        }


def test_run_ribon_check_no_update(monkeypatch, tmp_path):
    """When DB is current, update_available is False with no error."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")  # just needs to exist

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionNoUpdate(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is False
    assert result["error"] is None
    assert result["local_version"] == "3.5"


def test_run_ribon_check_incremental_update(monkeypatch, tmp_path):
    """Incremental sub-version update is detected."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionIncrementalUpdate(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is True
    assert result["update_type"] == "incremental"
    assert result["remote_version"] == "3.7"
    assert result["local_version"] == "3.5"


def test_run_ribon_check_major_update(monkeypatch, tmp_path):
    """Major version change is detected."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionMajorUpdate(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is True
    assert result["update_type"] == "major"
    assert result["remote_version"] == "4.0"


def test_run_ribon_check_db_not_found(monkeypatch):
    """When the .accdb file doesn't exist, return db_not_found error."""
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )

    result = run_ribon_check(db_path=r"C:\nonexistent\Ribon.accdb")

    assert result["update_available"] is False
    assert result["error"] == "db_not_found"


def test_run_ribon_check_db_read_error(monkeypatch, tmp_path):
    """When DB read raises an exception, it's captured as db_read_error."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    def _failing_read(_db_path):
        raise RuntimeError("mock ODBC failure")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _failing_read,
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is False
    assert result["error"] is not None
    assert result["error"].startswith("db_read_error")


def test_run_ribon_check_connection_error(monkeypatch, tmp_path):
    """Web service unreachable → ws_unreachable error."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    import requests

    def _failing_ws(*args, **kwargs):
        raise requests.exceptions.ConnectionError("mock offline")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _failing_ws,
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is False
    assert result["error"] is not None
    assert result["error"].startswith("ws_unreachable")


def test_run_ribon_check_timeout(monkeypatch, tmp_path):
    """Web service timeout → ws_timeout error."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    import requests

    def _timeout_ws(*args, **kwargs):
        raise requests.exceptions.Timeout("mock timeout")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _timeout_ws,
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["error"] is not None
    assert result["error"].startswith("ws_timeout")


def test_run_ribon_check_ws_flag_zero(monkeypatch, tmp_path):
    """flag=0 from server → ws_flag_zero error."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionFlagZero(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is False
    assert result["error"] == "ws_flag_zero"


def test_run_ribon_check_unparseable_remote_version(monkeypatch, tmp_path):
    """Server returns unparseable new_sub_version → error captured."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    class _BadVersionWS:
        @staticmethod
        def __call__(*args, **kwargs):
            return {
                "flag": "1",
                "file_name": "",
                "size": "",
                "new_sub_version": "not_a_number",
                "new_main_version": "3.5",
            }

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _BadVersionWS(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["update_available"] is False
    assert result["error"] is not None
    assert result["error"].startswith("unparseable_version")


def test_run_ribon_check_empty_db_version_handled(monkeypatch, tmp_path):
    """Empty CURRENT_DATA_VERSION → (0,0) local version.

    The server reports new_main_version == "3.5" with new_sub_version == "0".
    Since local is empty and remote isn't, this is treated as a major
    version change.
    """
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    class _EmptyVersionDB:
        @staticmethod
        def __call__(_db_path):
            return {
                "current_data_version": "",
                "current_soft_version": "",
                "current_install_key": None,
                "bsi_flg": "1",
                "country_type": "0",
            }

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _EmptyVersionDB(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionNoUpdate(),
    )

    result = run_ribon_check(db_path=str(fake_db))

    assert result["local_version"] == "0.0"
    assert result["update_available"] is True
    assert result["update_type"] == "major"


# ============================================================================
# RibonCheckWorker signal smoke test
# ============================================================================


from pmgen.io.ribon_update_check import RibonCheckWorker  # noqa: E402


class _SignalSpy:
    """Capture the last signal emission from a QObject."""

    def __init__(self):
        self.calls: list[tuple] = []

    def slot(self, *args):
        self.calls.append(args)


def test_ribon_check_worker_emits_result(monkeypatch, tmp_path, qtbot):
    """Worker.run_check emits check_finished with the right shape."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._read_setup_info_isolated",
        _FakeSetupInfoForCheck(),
    )
    monkeypatch.setattr(
        "pmgen.io.ribon_update_check._call_check_version",
        _FakeCheckVersionNoUpdate(),
    )

    worker = RibonCheckWorker(db_path=str(fake_db))
    spy = _SignalSpy()
    worker.check_finished.connect(spy.slot)

    worker.run_check()

    assert len(spy.calls) == 1
    update_available, result = spy.calls[0]
    assert update_available is False
    assert result["local_version"] == "3.5"
    assert result["error"] is None


def test_ribon_check_worker_crash_is_caught(monkeypatch, tmp_path, qtbot):
    """If run_ribon_check itself raises unexpectedly, the worker catches it."""
    fake_db = tmp_path / "Ribon.accdb"
    fake_db.write_text("")

    def _explode(_db_path, timeout=15):
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(
        "pmgen.io.ribon_update_check.run_ribon_check",
        _explode,
    )

    worker = RibonCheckWorker(db_path=str(fake_db))
    spy = _SignalSpy()
    worker.check_finished.connect(spy.slot)

    worker.run_check()

    assert len(spy.calls) == 1
    update_available, result = spy.calls[0]
    assert update_available is False
    assert "worker_crash" in result.get("error", "")
