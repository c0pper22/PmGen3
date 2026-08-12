import os
from types import SimpleNamespace

import pandas as pd

from pmgen.rules.inventory_check import InventoryCheckRule
from pmgen.ui import inventory


def _write_inventory(path, quantity: int = 3) -> None:
    path.write_text(
        "Part Number,Unit Name,Quantity\n"
        f"PN-100,PRIMARY UNIT,{quantity}\n",
        encoding="utf-8",
    )


def test_inventory_snapshot_reuses_normalized_csv_until_file_changes(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()

    original_read_csv = pd.read_csv
    read_count = 0

    def counted_read_csv(*args, **kwargs):
        nonlocal read_count
        read_count += 1
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(inventory.pd, "read_csv", counted_read_csv)

    first = inventory.load_inventory_snapshot()
    second = inventory.load_inventory_snapshot()

    assert first is second
    assert read_count == 1
    assert first.find_match("pn-100") == (3.0, "PRIMARY UNIT")

    previous_mtime = cache_path.stat().st_mtime_ns
    _write_inventory(cache_path, quantity=7)
    os.utime(cache_path, ns=(previous_mtime + 1_000_000_000, previous_mtime + 1_000_000_000))

    changed = inventory.load_inventory_snapshot()

    assert changed is not first
    assert read_count == 2
    assert changed.find_match("PN-100") == (7.0, "PRIMARY UNIT")


def test_inventory_cache_explicit_invalidation_forces_reload(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()

    first = inventory.load_inventory_snapshot()
    inventory.invalidate_inventory_cache()
    second = inventory.load_inventory_snapshot()

    assert second is not first


def test_inventory_cache_retries_after_transient_read_failure(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()
    original_read_csv = pd.read_csv
    attempts = 0

    def flaky_read_csv(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("temporarily unavailable")
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(inventory.pd, "read_csv", flaky_read_csv)

    assert inventory.load_inventory_snapshot().is_empty
    recovered = inventory.load_inventory_snapshot()

    assert attempts == 2
    assert recovered.find_match("PN-100") == (3.0, "PRIMARY UNIT")


def test_inventory_cache_uses_last_snapshot_after_transient_stat_failure(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()
    expected = inventory.load_inventory_snapshot()

    monkeypatch.setattr(inventory.os, "stat", lambda path: (_ for _ in ()).throw(PermissionError("busy")))

    assert inventory.load_inventory_snapshot() is expected


def test_inventory_cache_reads_valid_zero_mtime_file(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    os.utime(cache_path, ns=(0, 0))
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()

    snapshot = inventory.load_inventory_snapshot()

    assert snapshot.find_match("PN-100") == (3.0, "PRIMARY UNIT")


def test_legacy_inventory_dataframe_cannot_mutate_cached_snapshot(tmp_path, monkeypatch):
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()

    dataframe = inventory.load_inventory_cache()
    dataframe.loc[0, "Quantity"] = 99

    assert inventory.load_inventory_snapshot().find_match("PN-100") == (3.0, "PRIMARY UNIT")


def test_inventory_snapshot_preserves_first_matching_row():
    dataframe = pd.DataFrame(
        [
            {"Part Number": "OTHER", "Unit Name": "KIT-1 ASSEMBLY", "Quantity": 2},
            {"Part Number": "KIT-1", "Unit Name": "EXACT PART", "Quantity": 9},
        ]
    )

    snapshot = inventory.InventorySnapshot.from_dataframe(dataframe)

    assert snapshot.find_match("kit-1") == (2.0, "KIT-1 ASSEMBLY")


def test_inventory_autosave_atomically_refreshes_cached_snapshot(tmp_path, monkeypatch, qtbot):
    tab = inventory.InventoryTab()
    qtbot.addWidget(tab)
    cache_path = tmp_path / "inventory.csv"
    _write_inventory(cache_path, quantity=1)
    monkeypatch.setattr(inventory, "get_cache_path", lambda: str(cache_path))
    inventory.invalidate_inventory_cache()
    assert inventory.load_inventory_snapshot().find_match("PN-100") == (1.0, "PRIMARY UNIT")

    dataframe = pd.DataFrame(
        [{"Part Number": "PN-100", "Unit Name": "PRIMARY UNIT", "Quantity": 4}]
    )
    monkeypatch.setattr(tab.model, "get_dataframe", lambda: dataframe)
    monkeypatch.setattr(tab, "_get_cache_path", lambda: str(cache_path))

    tab._auto_save_to_cache()

    assert cache_path.exists()
    assert inventory.load_inventory_snapshot().find_match("PN-100") == (4.0, "PRIMARY UNIT")
    assert list(tmp_path.glob("*.tmp")) == []


def test_inventory_rule_uses_snapshot_match(monkeypatch):
    snapshot = inventory.InventorySnapshot.from_dataframe(
        pd.DataFrame(
            [{"Part Number": "KIT-1", "Unit Name": "PRIMARY UNIT", "Quantity": 4}]
        )
    )
    monkeypatch.setattr(inventory, "load_inventory_snapshot", lambda: snapshot)
    context = SimpleNamespace(
        kit_selection={"kit-1": 3},
        meta={},
        optional_alerts=[],
    )

    InventoryCheckRule().apply(context)

    assert context.meta["inventory_matches"] == [
        {
            "code": "kit-1",
            "matched_with": "PRIMARY UNIT",
            "needed": 3,
            "in_stock": 4.0,
            "covered": 3,
        }
    ]