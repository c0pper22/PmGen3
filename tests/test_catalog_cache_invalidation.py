"""Cache-invalidation regression tests for the catalog-driven rule caches.

The rules engine keeps three independent in-memory caches that mirror the
SQLite catalog so the pipeline does not hit the database on every report:

* ``pmgen.canon.canon_utils._MAPPINGS_CACHE``  -> ``canon_unit()``
* ``pmgen.rules.kit_link.KitLinkRule._CACHE``   -> canon -> kit code
* ``pmgen.rules.grouping.UnitGroupingRule._PER_COLOR_CACHE`` -> per-color units
* ``pmgen.rules.qty_override.QtyOverrideRule`` overrides -> fixed kit quantities

The catalog editor mutates the SQLite database and is responsible for
invalidating these caches so edits take effect without an app restart.

These tests prove the invalidation contract end to end: each cache must
return stale data after a DB edit *until* it is cleared, and fresh data
afterwards. They use a throwaway SQLite database in a per-test temp
directory (``get_db_path()`` resolves to ``$CWD/catalog_manager.db`` in
source mode) so the real bundled catalog is never touched.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from pmgen.canon.canon_utils import canon_unit, reload_mappings_cache
from pmgen.engine.run_rules import PIPELINE
from pmgen.io.db_access import CatalogDB
from pmgen.rules.base import Context
from pmgen.rules.grouping import UnitGroupingRule
from pmgen.rules.kit_link import KitLinkRule
from pmgen.rules.qty_override import QtyOverrideRule
from pmgen.types import Finding, PmReport
from pmgen.ui.catalog_editor import QtyOverridesTab


def _reset_caches() -> None:
    """Clear every catalog cache so tests start from a known-empty state."""
    reload_mappings_cache()
    KitLinkRule.clear_cache()
    UnitGroupingRule.clear_cache()
    if hasattr(QtyOverrideRule, "clear_cache"):
        QtyOverrideRule.clear_cache()


def _ctx(kit_selection: dict[str, int]) -> Context:
    return Context(
        report=PmReport(),
        model="",
        items_by_canon={},
        threshold=0.8,
        life_basis="page",
        kit_selection=dict(kit_selection),
    )


def _ctx_with_finding(model: str, canon: str) -> Context:
    return Context(
        report=PmReport(),
        model=model,
        items_by_canon={},
        threshold=0.8,
        life_basis="page",
        findings={canon: Finding(canon=canon, due=True)},
    )


def _ctx_with_findings(findings: list[Finding]) -> Context:
    return Context(
        report=PmReport(),
        model="",
        items_by_canon={},
        threshold=0.8,
        life_basis="page",
        findings={f.canon: f for f in findings},
    )


def test_canon_mappings_cache_refreshes_after_reload(tmp_path, monkeypatch):
    """canon_unit() must reflect newly added canon mappings after reload_mappings_cache()."""
    monkeypatch.chdir(tmp_path)
    _reset_caches()

    db = CatalogDB()
    # Empty catalog: nothing canonizes yet.
    assert canon_unit("DRUM (K)") is None

    db.add_mapping(r"^DRUM{SPC}{LP}{COLOR}{RP}$", "DRUM[{chan}]")

    # Stale cache still has no mappings -> still None.
    assert canon_unit("DRUM (K)") is None

    reload_mappings_cache()

    assert canon_unit("DRUM (K)") == "DRUM[K]"


def test_kit_link_cache_refreshes_after_clear_cache(tmp_path, monkeypatch):
    """KitLinkRule must reflect unit-item edits after clear_cache()."""
    monkeypatch.chdir(tmp_path)
    _reset_caches()

    db = CatalogDB()
    db.add_model("E-STUDIO 556")
    db.add_unit("EPU-KIT-FC556-G")
    db.link_unit_to_model("E-STUDIO 556", "EPU-KIT-FC556-G")

    rule = KitLinkRule()
    ctx0 = _ctx_with_finding("E-STUDIO 556", "DRUM[K]")
    rule.apply(ctx0)
    # Unit has no canon items yet -> no kit link.
    assert ctx0.findings["DRUM[K]"].kit_code is None

    db.replace_items_for_unit("EPU-KIT-FC556-G", ["DRUM[K]"])

    # Stale cache still maps nothing.
    ctx_stale = _ctx_with_finding("E-STUDIO 556", "DRUM[K]")
    rule.apply(ctx_stale)
    assert ctx_stale.findings["DRUM[K]"].kit_code is None

    KitLinkRule.clear_cache()

    ctx_fresh = _ctx_with_finding("E-STUDIO 556", "DRUM[K]")
    rule.apply(ctx_fresh)
    assert ctx_fresh.findings["DRUM[K]"].kit_code == "EPU-KIT-FC556-G"


def test_per_color_cache_refreshes_after_clear_cache(tmp_path, monkeypatch):
    """UnitGroupingRule must reflect per-color flag edits after clear_cache()."""
    monkeypatch.chdir(tmp_path)
    _reset_caches()

    db = CatalogDB()
    db.add_unit("PC-KIT")
    db.add_per_color_unit("PC-KIT")

    findings = [
        Finding(canon="DRUM[K]", due=True, kit_code="PC-KIT"),
        Finding(canon="BLADE[K]", due=True, kit_code="PC-KIT"),
    ]

    rule = UnitGroupingRule()
    ctx = _ctx_with_findings(findings)
    rule.apply(ctx)
    # Per-color kit counts once per color -> two [K] findings collapse to 1.
    assert ctx.kit_selection["PC-KIT"] == 1

    db.remove_per_color_unit("PC-KIT")

    # Stale cache still treats PC-KIT as per-color -> still 1.
    ctx_stale = _ctx_with_findings(findings)
    rule.apply(ctx_stale)
    assert ctx_stale.kit_selection["PC-KIT"] == 1

    UnitGroupingRule.clear_cache()

    ctx_fresh = _ctx_with_findings(findings)
    rule.apply(ctx_fresh)
    # No longer per-color: DRUM[K] and BLADE[K] are distinct buckets -> 2.
    assert ctx_fresh.kit_selection["PC-KIT"] == 2


def test_qty_override_singleton_refreshes_after_clear_cache(tmp_path, monkeypatch):
    """The PIPELINE singleton QtyOverrideRule must reflect override edits after clear_cache().

    This reproduces the stale-cache bug: the singleton instance is constructed
    once at import time, so without clear_cache() an edited override never
    takes effect until the app is restarted.
    """
    monkeypatch.chdir(tmp_path)
    _reset_caches()

    db = CatalogDB()
    db.add_unit("QO-TEST-KIT")

    # The same instance the production pipeline uses.
    singleton = next(rule for rule in PIPELINE if rule.name == "QtyOverrideRule")

    ctx0 = _ctx({"QO-TEST-KIT": 2})
    singleton.apply(ctx0)
    assert ctx0.kit_selection["QO-TEST-KIT"] == 2  # no override yet

    db.set_qty_override("QO-TEST-KIT", 5)

    QtyOverrideRule.clear_cache()

    ctx1 = _ctx({"QO-TEST-KIT": 2})
    singleton.apply(ctx1)
    assert ctx1.kit_selection["QO-TEST-KIT"] == 5


def test_qty_overrides_tab_save_clears_rule_cache(qtbot, tmp_path, monkeypatch):
    """QtyOverridesTab.save_changes() must refresh the QtyOverrideRule cache.

    End-to-end check using the real editor tab and the real PIPELINE singleton:
    after saving an override through the tab, the same singleton rule instance
    must apply the new quantity without an app restart.
    """
    monkeypatch.chdir(tmp_path)
    _reset_caches()

    db = CatalogDB()
    db.add_unit("QO-TEST-KIT")

    singleton = next(rule for rule in PIPELINE if rule.name == "QtyOverrideRule")
    ctx0 = _ctx({"QO-TEST-KIT": 1})
    singleton.apply(ctx0)
    assert ctx0.kit_selection["QO-TEST-KIT"] == 1  # no override yet

    tab = QtyOverridesTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 1).text() == "QO-TEST-KIT")
    tab.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    tab.table.item(row, 2).setText("5")

    tab.save_changes()

    assert db.get_qty_overrides() == {"QO-TEST-KIT": 5}

    ctx1 = _ctx({"QO-TEST-KIT": 1})
    singleton.apply(ctx1)
    assert ctx1.kit_selection["QO-TEST-KIT"] == 5
