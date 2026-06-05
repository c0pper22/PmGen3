from pathlib import Path

from PyQt6.QtCore import Qt

from pmgen.io.db_access import CatalogDB
from pmgen.ui.catalog_editor import CanonMappingsTab, CatalogEditorWindow, PerColorUnitsTab, QtyOverridesTab, UnitsTab


def test_catalog_editor_is_frameless(qtbot):
    window = CatalogEditorWindow(icon_dir="", parent=None)
    qtbot.addWidget(window)

    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint)


def test_catalog_editor_marks_dirty_tabs_and_save_all_state(qtbot):
    window = CatalogEditorWindow(icon_dir="", parent=None)
    qtbot.addWidget(window)

    tab_index = window.tabs.indexOf(window.tab_units)

    assert window.tabs.tabText(tab_index) == "PM Units"
    assert not window.btn_save_all.isEnabled()

    window.tab_units._set_dirty(True)

    assert window.tabs.tabText(tab_index) == "PM Units *"
    assert window.btn_save_all.isEnabled()

    window.tab_units._set_dirty(False)

    assert window.tabs.tabText(tab_index) == "PM Units"
    assert not window.btn_save_all.isEnabled()


def test_catalog_editor_save_all_saves_dirty_tabs_in_dependency_order(qtbot, monkeypatch):
    window = CatalogEditorWindow(icon_dir="", parent=None)
    qtbot.addWidget(window)
    calls = []

    def fake_save(tab, name):
        calls.append(name)
        tab._set_dirty(False)

    monkeypatch.setattr(window.tab_units, "save_changes", lambda: fake_save(window.tab_units, "units"))
    monkeypatch.setattr(window.tab_models, "save_changes", lambda: fake_save(window.tab_models, "models"))
    monkeypatch.setattr(window.tab_qty, "save_changes", lambda: fake_save(window.tab_qty, "qty"))

    window.tab_models._set_dirty(True)
    window.tab_units._set_dirty(True)
    window.tab_qty._set_dirty(True)

    window.save_all_changes()

    assert calls == ["units", "models", "qty"]
    assert not window.btn_save_all.isEnabled()


def test_catalog_editor_shows_general_dependency_hint_for_any_dirty_tab(qtbot):
    window = CatalogEditorWindow(icon_dir="", parent=None)
    qtbot.addWidget(window)

    assert window.dependency_hint.isHidden()

    window.tab_models._set_dirty(True)

    assert not window.dependency_hint.isHidden()
    assert window.dependency_hint.text() == (
        "Save changes to make updated catalog data available across all Catalog Editor tabs."
    )

    window.tab_models._set_dirty(False)

    assert window.dependency_hint.isHidden()


def test_catalog_editor_dependency_hint_stays_visible_when_switching_tabs(qtbot):
    window = CatalogEditorWindow(icon_dir="", parent=None)
    qtbot.addWidget(window)

    window.tab_qty._set_dirty(True)

    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        assert not window.dependency_hint.isHidden()
        assert window.dependency_hint.text() == (
            "Save changes to make updated catalog data available across all Catalog Editor tabs."
        )

    window.tab_qty._set_dirty(False)


class _FakeMappingsDB:
    def __init__(self, mappings):
        self._mappings = mappings

    def get_mappings(self):
        return list(self._mappings)

    def add_mapping(self, pattern, template):
        self._mappings.append((9999, pattern, template))

    def update_mapping(self, mapping_id, pattern, template):
        for index, (mid, _pattern, _template) in enumerate(self._mappings):
            if mid == mapping_id:
                self._mappings[index] = (mid, pattern, template)
                return

    def delete_mapping(self, mapping_id):
        self._mappings = [m for m in self._mappings if m[0] != mapping_id]


def test_canon_mappings_tab_validates_builtin_tokens(qtbot):
    db = _FakeMappingsDB(
        [
            (1, r"^DRUM{SPC}{LP}{COLOR}{RP}$", "DRUM[{chan}]"),
        ]
    )
    tab = CanonMappingsTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    assert tab._validate() is None


def test_canon_mappings_tab_rejects_unknown_token(qtbot):
    db = _FakeMappingsDB(
        [
            (1, r"^DRUM{SPC}{MISSING_TOKEN}$", "DRUM[{chan}]"),
        ]
    )
    tab = CanonMappingsTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    err = tab._validate()
    assert err is not None
    assert "Unknown regex token" in err


def test_canon_mappings_tab_global_tester_finds_first_match(qtbot):
    db = _FakeMappingsDB(
        [
            (1, r"^DRUM{SPC}{LP}{COLOR}{RP}$", "DRUM[{chan}]"),
            (2, r"^DRUM$", "DRUM[K]"),
        ]
    )
    tab = CanonMappingsTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    tab.test_input.setText("DRUM (K)")
    tab._run_global_test()

    out = tab.test_result.toPlainText()
    assert "Matched row: 1" in out
    assert "Output: DRUM[K]" in out


def test_catalog_db_available_canon_items_expands_channel_templates(monkeypatch):
    temp_dir = Path("tmp_test_data")
    temp_dir.mkdir(exist_ok=True)
    db_path = temp_dir / "catalog_manager.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr("pmgen.io.db_access.get_db_path", lambda: str(db_path))

    db = CatalogDB()
    db.add_mapping(r"^DRUM(?P<chan>K|C|M|Y)$", "DRUM[{chan}]")
    db.add_mapping(r"^FUSER$", "FUSER BELT")

    assert db.get_available_canon_items() == [
        "DRUM[C]",
        "DRUM[K]",
        "DRUM[M]",
        "DRUM[Y]",
        "FUSER BELT",
    ]


class _FakeUnitsDB:
    def __init__(self):
        self.saved_items = []

    def get_available_canon_items(self):
        return ["DRUM[C]", "DRUM[K]", "FUSER BELT"]

    def get_all_units(self):
        return ["UNIT-A"]

    def get_items_for_unit(self, unit_name):
        assert unit_name == "UNIT-A"
        return ["DRUM[K]"]

    def replace_items_for_unit(self, unit_name, items):
        self.saved_items.append((unit_name, items))


def test_units_tab_selects_canon_items_from_mapping_list(qtbot):
    tab = UnitsTab(db=_FakeUnitsDB(), icon_dir="", parent=None)
    qtbot.addWidget(tab)

    displayed_items = [tab.item_checks.item(i).text() for i in range(tab.item_checks.count())]
    assert displayed_items == ["DRUM[C]", "DRUM[K]", "FUSER BELT"]
    assert tab.item_checks.item(displayed_items.index("DRUM[K]")).checkState() == Qt.CheckState.Checked

    tab.item_checks.item(displayed_items.index("DRUM[C]")).setCheckState(Qt.CheckState.Checked)

    assert tab._get_row_items(0) == {"DRUM[C]", "DRUM[K]"}
    assert tab.is_dirty


def test_units_tab_rejects_items_missing_from_canon_mappings(qtbot):
    db = _FakeUnitsDB()
    tab = UnitsTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    tab._set_row_items(0, {"DRUM[K]", "MADE UP ITEM"})

    err = tab._validate()

    assert err is not None
    assert "MADE UP ITEM" in err


class _FakePerColorUnitsDB:
    def __init__(self):
        self.per_color_units = {"UNIT-B"}
        self.added = []
        self.removed = []

    def get_all_units(self):
        return ["UNIT-A", "UNIT-B", "UNIT-C"]

    def get_per_color_units(self):
        return sorted(self.per_color_units)

    def add_per_color_unit(self, unit_name):
        self.added.append(unit_name)
        self.per_color_units.add(unit_name)

    def remove_per_color_unit(self, unit_name):
        self.removed.append(unit_name)
        self.per_color_units.discard(unit_name)


def test_per_color_units_tab_selects_pm_units_from_list(qtbot):
    tab = PerColorUnitsTab(db=_FakePerColorUnitsDB(), icon_dir="", parent=None)
    qtbot.addWidget(tab)

    displayed_units = [tab.unit_checks.item(i).text() for i in range(tab.unit_checks.count())]
    assert displayed_units == ["UNIT-A", "UNIT-B", "UNIT-C"]
    assert tab.unit_checks.item(displayed_units.index("UNIT-B")).checkState() == Qt.CheckState.Checked

    tab.unit_checks.item(displayed_units.index("UNIT-C")).setCheckState(Qt.CheckState.Checked)

    assert tab._current_values() == {"UNIT-B", "UNIT-C"}
    assert tab.is_dirty


def test_per_color_units_tab_saves_checked_unit_changes(qtbot):
    db = _FakePerColorUnitsDB()
    tab = PerColorUnitsTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    displayed_units = [tab.unit_checks.item(i).text() for i in range(tab.unit_checks.count())]
    tab.unit_checks.item(displayed_units.index("UNIT-A")).setCheckState(Qt.CheckState.Checked)
    tab.unit_checks.item(displayed_units.index("UNIT-B")).setCheckState(Qt.CheckState.Unchecked)

    tab.save_changes()

    assert db.added == ["UNIT-A"]
    assert db.removed == ["UNIT-B"]
    assert db.per_color_units == {"UNIT-A"}


class _FakeQtyOverridesDB:
    def __init__(self):
        self.overrides = {"UNIT-B": 2}
        self.set_calls = []
        self.deleted = []

    def get_all_units(self):
        return ["UNIT-A", "UNIT-B", "UNIT-C"]

    def get_qty_overrides(self):
        return dict(self.overrides)

    def set_qty_override(self, unit_name, quantity):
        self.set_calls.append((unit_name, quantity))
        self.overrides[unit_name] = quantity

    def delete_qty_override(self, unit_name):
        self.deleted.append(unit_name)
        self.overrides.pop(unit_name, None)


def test_qty_overrides_tab_selects_pm_units_from_list(qtbot):
    tab = QtyOverridesTab(db=_FakeQtyOverridesDB(), icon_dir="", parent=None)
    qtbot.addWidget(tab)

    displayed_units = [tab.table.item(row, 1).text() for row in range(tab.table.rowCount())]
    assert displayed_units == ["UNIT-A", "UNIT-B", "UNIT-C"]
    assert tab.table.item(displayed_units.index("UNIT-B"), 0).checkState() == Qt.CheckState.Checked
    assert tab.table.item(displayed_units.index("UNIT-B"), 2).text() == "2"

    unit_a_row = displayed_units.index("UNIT-A")
    tab.table.item(unit_a_row, 0).setCheckState(Qt.CheckState.Checked)
    tab.table.item(unit_a_row, 2).setText("4")

    assert tab._current_values() == {"UNIT-A": 4, "UNIT-B": 2}
    assert tab.is_dirty


def test_qty_overrides_tab_saves_checked_unit_changes(qtbot):
    db = _FakeQtyOverridesDB()
    tab = QtyOverridesTab(db=db, icon_dir="", parent=None)
    qtbot.addWidget(tab)

    displayed_units = [tab.table.item(row, 1).text() for row in range(tab.table.rowCount())]
    unit_a_row = displayed_units.index("UNIT-A")
    unit_b_row = displayed_units.index("UNIT-B")

    tab.table.item(unit_a_row, 0).setCheckState(Qt.CheckState.Checked)
    tab.table.item(unit_a_row, 2).setText("3")
    tab.table.item(unit_b_row, 0).setCheckState(Qt.CheckState.Unchecked)

    tab.save_changes()

    assert db.set_calls == [("UNIT-A", 3)]
    assert db.deleted == ["UNIT-B"]
    assert db.overrides == {"UNIT-A": 3}
