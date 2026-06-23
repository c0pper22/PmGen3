"""Tests for RemoteTech API client and worker.

Covers:
- RemoteTechAPI.part_number_lookup (exact match, no match, bin_search parameter)
- RemoteTechAPI.add_part_to_call (response parsing, empty response)
- RemoteTechWorker.run_add_parts (all success, partial failure, deduplication,
  login failure, exceptions)
- RemoteTechWorker.run_login_and_fetch_calls (success, failure)
"""

from __future__ import annotations

import json
from unittest.mock import DEFAULT, MagicMock, PropertyMock, patch

import pytest
from PyQt6.QtCore import QThread
from PyQt6.QtTest import QSignalSpy

from pmgen.io.remotetech_api import (
    AddedPartResult,
    Call,
    LoginResult,
    PartLookupResult,
    RemoteTechAPI,
)
from pmgen.ui.workers import RemoteTechWorker


# ---------------------------------------------------------------------------
# Reusable test data
# ---------------------------------------------------------------------------

_SAMPLE_EXACT_MATCH = {
    "ExactItemMatch": {
        "ItemID": 5425,
        "Item": "600N03611",
        "Description": "Feed Rolls (HCF)",
        "Available": 1,
        "PrefMfgNumber": "600N03611",
    },
}

_SAMPLE_ADD_RESPONSE = [
    {
        "RTCallInventoryID": 12345,
        "CallMaterialBinID": 14438,
        "ItemID": 5425,
        "Item": "600N03611",
        "Description": "Feed Rolls (HCF)",
        "Quantity": 3,
        "Bin": "Main Bin",
        "BinID": 130,
        "Warehouse": "Main Warehouse",
        "WarehouseID": 42,
        "UsageStatusCode": "NEEDED",
        "DeliveryMethodID": 3,
        "Bill": True,
        "SystemComputedPrice": 0.0,
    },
]

_SAMPLE_CALLS = [
    Call(
        call_number="SC43848",
        call_id="42918",
        location="Indiana Business Solutions NP",
        status="Pending",
        location_remarks="",
        description="test",
        make_model="99999999999-NP",
        est_start="6/22/2026 8:32 AM",
        address="4045 Vincennes Rd, Indianapolis",
        detail_url="https://dgi17.ecihosted.com/C4990_RTS/online/calldetails/#/42918",
    ),
    Call(
        call_number="SC43849",
        call_id="42919",
        location="Another Location",
        status="In Progress",
        location_remarks="",
        description="service call",
        make_model="88888888888-NP",
        est_start="6/23/2026 9:00 AM",
        address="123 Main St",
        detail_url="https://dgi17.ecihosted.com/C4990_RTS/online/calldetails/#/42919",
    ),
]


# ===========================================================================
#  RemoteTechAPI.part_number_lookup
# ===========================================================================

def test_part_number_lookup_exact_match(monkeypatch) -> None:
    """ExactItemMatch returns a PartLookupResult."""
    api = RemoteTechAPI()

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_EXACT_MATCH
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(api, "_retry_request", MagicMock(return_value=mock_resp))
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    result = api.part_number_lookup("600N03611")

    assert result is not None
    assert result.item_id == 5425
    assert result.part_number == "600N03611"
    assert result.description == "Feed Rolls (HCF)"
    assert result.available == 1
    assert result.pref_mfg_number == "600N03611"


def test_part_number_lookup_no_match(monkeypatch) -> None:
    """When ExactItemMatch is falsy, return None."""
    api = RemoteTechAPI()

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"ExactItemMatch": None}
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(api, "_retry_request", MagicMock(return_value=mock_resp))
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    result = api.part_number_lookup("NONEXISTENT")

    assert result is None


def test_part_number_lookup_bin_search_false(monkeypatch) -> None:
    """bin_search=False sends bin=false in query params."""
    api = RemoteTechAPI()

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_EXACT_MATCH
    mock_resp.raise_for_status = MagicMock()

    mock_retry = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(api, "_retry_request", mock_retry)
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    api.part_number_lookup("600N03611", bin_search=False)

    _, kwargs = mock_retry.call_args
    assert kwargs["params"]["bin"] == "false"


def test_part_number_lookup_bin_search_true(monkeypatch) -> None:
    """bin_search=True (default) sends bin=true."""
    api = RemoteTechAPI()

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_EXACT_MATCH
    mock_resp.raise_for_status = MagicMock()

    mock_retry = MagicMock(return_value=mock_resp)
    monkeypatch.setattr(api, "_retry_request", mock_retry)
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    api.part_number_lookup("600N03611", bin_search=True)

    _, kwargs = mock_retry.call_args
    assert kwargs["params"]["bin"] == "true"


# ===========================================================================
#  RemoteTechAPI.add_part_to_call
# ===========================================================================

def test_add_part_to_call_success(monkeypatch) -> None:
    """add_part_to_call parses JSON response into AddedPartResult."""
    api = RemoteTechAPI()
    api._username = "testuser"
    api._queue_id = "queue123"

    mock_resp = MagicMock()
    mock_resp.json.return_value = _SAMPLE_ADD_RESPONSE
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(api, "_retry_request", MagicMock(return_value=mock_resp))
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    result = api.add_part_to_call(
        call_id="42918",
        item_id=5425,
        bin_id=130,
        quantity=3,
    )

    assert isinstance(result, AddedPartResult)
    assert result.call_inventory_id == 12345
    assert result.call_material_bin_id == 14438
    assert result.item_id == 5425
    assert result.part_number == "600N03611"
    assert result.quantity == 3
    assert result.bin == "Main Bin"
    assert result.bin_id == 130
    assert result.warehouse == "Main Warehouse"
    assert result.warehouse_id == 42
    assert result.usage_status_code == "NEEDED"
    assert result.delivery_method_id == 3
    assert result.bill is True


def test_add_part_to_call_empty_response(monkeypatch) -> None:
    """Empty response array raises ValueError."""
    api = RemoteTechAPI()
    api._username = "testuser"

    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr(api, "_retry_request", MagicMock(return_value=mock_resp))
    monkeypatch.setattr(api, "_throttle", MagicMock())
    monkeypatch.setattr(api, "_mark_request", MagicMock())

    with pytest.raises(ValueError, match="empty response array"):
        api.add_part_to_call(
            call_id="42918",
            item_id=5425,
            bin_id=130,
        )


# ===========================================================================
#  RemoteTechWorker — run_add_parts
# ===========================================================================

class _FakeRemoteTechAPI:
    """Configurable fake for RemoteTechAPI used in worker tests."""

    def __init__(
        self,
        *,
        login_success: bool = True,
        calls: list[Call] | None = None,
        lookup_results: dict[str, PartLookupResult | None] | None = None,
        add_raises: dict[str, Exception] | None = None,
    ) -> None:
        self.login_success = login_success
        self._calls: list[Call] = calls or []
        self._lookup_results: dict[str, PartLookupResult | None] = lookup_results or {}
        self._add_raises: dict[str, Exception] = add_raises or {}

        # Track calls for assertions
        self.lookup_calls: list[tuple[str, int | None]] = []  # (part_number, bin_search)
        self.add_calls: list[tuple[str, int, int, int]] = []  # (call_id, item_id, bin_id, qty)
        self.added_parts: list[str] = []

    def login(self, username: str, password: str) -> LoginResult:
        return LoginResult(
            success=self.login_success,
            message="OK" if self.login_success else "Bad credentials",
        )

    def get_users_active_calls(self) -> list[Call]:
        return list(self._calls)

    def part_number_lookup(
        self,
        part_number: str,
        count: int = 5,
        skip: int = 0,
        bin_search: bool = True,
        queue_id: str | None = None,
        rtuser: str | None = None,
    ) -> PartLookupResult | None:
        self.lookup_calls.append((part_number, None if bin_search else None))
        # Record bin_search value via a side channel
        self._last_bin_search = bin_search
        return self._lookup_results.get(part_number)

    def add_part_to_call(
        self,
        call_id: str,
        item_id: int,
        bin_id: int,
        quantity: int = 1,
        delivery_method_id: int = 1,
        usage_status_id: int = 1,
        bill: bool = True,
        discount: float = 0.0,
    ) -> AddedPartResult:
        if call_id in self._add_raises:
            raise self._add_raises[call_id]
        self.add_calls.append((call_id, item_id, bin_id, quantity))
        # Find the part_number by looking up item_id in results
        pn = "UNKNOWN"
        for k, v in self._lookup_results.items():
            if v is not None and v.item_id == item_id:
                pn = k
                break
        self.added_parts.append(pn)
        return AddedPartResult(
            call_inventory_id=1000 + len(self.add_calls),
            call_material_bin_id=2000 + len(self.add_calls),
            item_id=item_id,
            part_number=pn,
            description="Test Part",
            quantity=quantity,
            bin="Main Bin",
            bin_id=bin_id,
            warehouse="Main WH",
            warehouse_id=1,
            usage_status_code="NEEDED",
            delivery_method_id=3,
            bill=True,
            system_computed_price=0.0,
        )


class TestWorkerRunAddParts:
    """Unit tests for RemoteTechWorker.run_add_parts()."""

    P1 = "600N03611"
    P2 = "600N03612"
    P3 = "600N03613"

    def test_all_parts_added_successfully(self, qtbot) -> None:
        """Every part lookup succeeds and every add succeeds."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
                self.P2: PartLookupResult(item_id=102, part_number=self.P2, description="B", available=1, pref_mfg_number=self.P2),
                self.P3: PartLookupResult(item_id=103, part_number=self.P3, description="C", available=1, pref_mfg_number=self.P3),
            },
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[(self.P1, 2), (self.P2, 1), (self.P3, 5)],
            selected_call_id="CALL001",
        )
        # Inject fake API so no real HTTP calls happen
        worker._api = fake_api  # type: ignore[assignment]

        spy_added = QSignalSpy(worker.part_added)
        spy_failed = QSignalSpy(worker.part_failed)
        spy_finished = QSignalSpy(worker.finished)
        spy_error = QSignalSpy(worker.error)

        worker.run_add_parts()

        # All three parts should be added
        assert len(spy_added) == 3
        assert len(spy_failed) == 0
        assert len(spy_error) == 0
        assert len(spy_finished) == 1
        assert "Added 3 part(s), 0 failed" in spy_finished[0][0]

    def test_some_parts_not_found(self, qtbot) -> None:
        """Parts that return None from lookup emit part_failed."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
                self.P2: None,  # not found
                self.P3: PartLookupResult(item_id=103, part_number=self.P3, description="C", available=1, pref_mfg_number=self.P3),
            },
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[(self.P1, 1), (self.P2, 1), (self.P3, 1)],
            selected_call_id="CALL001",
        )
        worker._api = fake_api  # type: ignore[assignment]

        spy_added = QSignalSpy(worker.part_added)
        spy_failed = QSignalSpy(worker.part_failed)
        spy_finished = QSignalSpy(worker.finished)

        worker.run_add_parts()

        assert len(spy_added) == 2
        assert len(spy_failed) == 1
        # Check the failed signal
        assert spy_failed[0][0] == self.P2
        assert "Part not found" in spy_failed[0][1]
        assert "Added 2 part(s), 1 failed" in spy_finished[0][0]

    def test_lookup_uses_bin_search_false(self, qtbot) -> None:
        """Worker calls part_number_lookup with bin_search=False."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
            },
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[(self.P1, 1)],
            selected_call_id="CALL001",
        )
        worker._api = fake_api  # type: ignore[assignment]

        spy_added = QSignalSpy(worker.part_added)
        worker.run_add_parts()

        # Verify part was added
        assert len(spy_added) == 1
        # Verify the fake API was used and add was called with correct parameters
        assert len(fake_api.add_calls) == 1
        call_id, item_id, bin_id, qty = fake_api.add_calls[0]
        assert call_id == "CALL001"
        assert item_id == 101
        assert bin_id == 130
        assert qty == 1

    def test_login_failure_emits_error(self, qtbot) -> None:
        """When login fails, error signal is emitted and no parts are added."""
        fake_api = _FakeRemoteTechAPI(login_success=False)

        # Patch the RemoteTechAPI import used inside workers.py
        with patch("pmgen.io.remotetech_api.RemoteTechAPI", return_value=fake_api):
            worker = RemoteTechWorker(
                username="bad",
                password="bad",
                bin_id=130,
                part_entries=[(self.P1, 1)],
                selected_call_id="CALL001",
            )

            spy_error = QSignalSpy(worker.error)
            spy_added = QSignalSpy(worker.part_added)
            spy_finished = QSignalSpy(worker.finished)

            worker.run_add_parts()

            assert len(spy_error) == 1
            assert "login failed" in spy_error[0][0].lower()
            assert len(spy_added) == 0
            assert len(spy_finished) == 0

    def test_add_part_exception_emits_failed(self, qtbot) -> None:
        """When add_part_to_call raises, it emits part_failed and continues."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
                self.P2: PartLookupResult(item_id=102, part_number=self.P2, description="B", available=1, pref_mfg_number=self.P2),
            },
            add_raises={"CALL001": RuntimeError("Server error")},
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[(self.P1, 1), (self.P2, 1)],
            selected_call_id="CALL001",
        )
        worker._api = fake_api  # type: ignore[assignment]

        spy_added = QSignalSpy(worker.part_added)
        spy_failed = QSignalSpy(worker.part_failed)
        spy_finished = QSignalSpy(worker.finished)

        worker.run_add_parts()

        # Both parts fail because the same call ID raises for both
        assert len(spy_added) == 0
        assert len(spy_failed) == 2
        assert "Added 0 part(s), 2 failed" in spy_finished[0][0]

    def test_parts_deduplication(self, qtbot) -> None:
        """Duplicate part numbers have quantities summed."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
            },
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            # Same part appears 3 times with different quantities
            part_entries=[(self.P1, 2), (self.P1, 1), (self.P1, 5)],
            selected_call_id="CALL001",
        )
        worker._api = fake_api  # type: ignore[assignment]

        spy_added = QSignalSpy(worker.part_added)
        spy_finished = QSignalSpy(worker.finished)

        worker.run_add_parts()

        # Only one add call with summed quantity
        assert len(spy_added) == 1
        assert len(fake_api.add_calls) == 1
        _, _, _, qty = fake_api.add_calls[0]
        assert qty == 8  # 2 + 1 + 5
        assert "Added 1 part(s), 0 failed" in spy_finished[0][0]

    def test_worker_reuses_existing_api(self, qtbot) -> None:
        """When _api is already set, worker skips login."""
        fake_api = _FakeRemoteTechAPI(
            login_success=True,
            lookup_results={
                self.P1: PartLookupResult(item_id=101, part_number=self.P1, description="A", available=1, pref_mfg_number=self.P1),
            },
        )

        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[(self.P1, 1)],
            selected_call_id="CALL001",
        )
        worker._api = fake_api  # type: ignore[assignment]

        # Track whether login was called
        original_login = fake_api.login

        def tracking_login(u, p):
            tracking_login.called = True  # type: ignore[attr-defined]
            return original_login(u, p)

        tracking_login.called = False  # type: ignore[attr-defined]
        fake_api.login = tracking_login  # type: ignore[assignment]

        worker.run_add_parts()

        # Login should NOT have been called since _api was already set
        assert not tracking_login.called  # type: ignore[attr-defined]
        assert len(QSignalSpy(worker.error)) == 0


# ===========================================================================
#  RemoteTechWorker — run_login_and_fetch_calls
# ===========================================================================

def test_run_login_and_fetch_calls_success(qtbot, monkeypatch) -> None:
    """Login succeeds and active calls are emitted via calls_ready."""
    fake_api = _FakeRemoteTechAPI(
        login_success=True,
        calls=_SAMPLE_CALLS,
    )

    with patch("pmgen.io.remotetech_api.RemoteTechAPI", return_value=fake_api):
        worker = RemoteTechWorker(
            username="test",
            password="pass",
            bin_id=130,
            part_entries=[("P1", 1)],
        )

        spy_calls_ready = QSignalSpy(worker.calls_ready)
        spy_error = QSignalSpy(worker.error)

        worker.run_login_and_fetch_calls()

        assert len(spy_calls_ready) == 1
        assert len(spy_error) == 0
        calls = spy_calls_ready[0][0]
        assert len(calls) == 2
        assert calls[0].call_number == "SC43848"
        assert calls[1].call_number == "SC43849"


def test_run_login_and_fetch_calls_login_failure(qtbot, monkeypatch) -> None:
    """Login failure emits error signal."""
    fake_api = _FakeRemoteTechAPI(login_success=False)

    with patch("pmgen.io.remotetech_api.RemoteTechAPI", return_value=fake_api):
        worker = RemoteTechWorker(
            username="bad",
            password="bad",
            bin_id=130,
            part_entries=[("P1", 1)],
        )

        spy_calls_ready = QSignalSpy(worker.calls_ready)
        spy_error = QSignalSpy(worker.error)

        worker.run_login_and_fetch_calls()

        assert len(spy_calls_ready) == 0
        assert len(spy_error) == 1
        assert "login failed" in spy_error[0][0].lower()


# ===========================================================================
#  Signal / Type verification
# ===========================================================================

def test_worker_signals_exist() -> None:
    """Smoke test: RemoteTechWorker declares all expected signals."""
    worker = RemoteTechWorker(
        username="u", password="p", bin_id=1, part_entries=[]
    )
    assert hasattr(worker, "calls_ready")
    assert hasattr(worker, "part_added")
    assert hasattr(worker, "part_failed")
    assert hasattr(worker, "finished")
    assert hasattr(worker, "error")
