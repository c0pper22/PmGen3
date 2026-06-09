from __future__ import annotations

import os
import re
import string
from typing import Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pmgen.canon.canon_utils import reload_mappings_cache
from pmgen.canon.regex_tokens import BUILTIN_REGEX_TOKENS, expand_regex_tokens
from pmgen.io.db_access import CatalogDB
from pmgen.rules.grouping import UnitGroupingRule
from pmgen.rules.kit_link import KitLinkRule
from pmgen.ui.components import CustomMessageBox, ResizeState
from pmgen.ui.shell import WindowControlSpec, WindowResizeMixin, build_frameless_top_bar
from pmgen.ui.theme import SPACING_LG, SPACING_MD


class _EditorTabBase(QWidget):
    dirty_changed = pyqtSignal(bool)

    def __init__(self, icon_dir: str, parent=None):
        super().__init__(parent)
        self._icon_dir = icon_dir
        self._is_dirty = False

    @property
    def is_dirty(self) -> bool:
        return self._is_dirty

    def _set_dirty(self, dirty: bool):
        if self._is_dirty == dirty:
            return
        self._is_dirty = dirty
        self.dirty_changed.emit(dirty)


class CanonMappingsTab(_EditorTabBase):
    def __init__(self, db: CatalogDB, icon_dir: str, parent=None):
        super().__init__(icon_dir, parent)
        self._db = db
        self._loading = False
        self._deleted_ids: Set[int] = set()

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.info = QLabel("Regex pattern → canonical template (supports {TOKEN} regex helpers)")
        self.info.setObjectName("DialogLabel")
        top.addWidget(self.info, 1)

        self.btn_add = QPushButton("Add")
        self.btn_remove = QPushButton("Delete")
        self.btn_save = QPushButton("Save")
        self.btn_discard = QPushButton("Discard")
        self.btn_add.clicked.connect(self._add_row)
        self.btn_remove.clicked.connect(self._delete_selected)
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_discard.clicked.connect(self.load_data)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_discard)
        root.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ID", "Pattern", "Template"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 420)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        token_row = QHBoxLayout()
        token_title = QLabel("Regex tokens (optional helper)")
        token_title.setObjectName("DialogLabel")
        token_row.addWidget(token_title, 1)
        self.btn_toggle_tokens = QPushButton("Show Tokens")
        self.btn_toggle_tokens.clicked.connect(self._toggle_token_table)
        token_row.addWidget(self.btn_toggle_tokens)
        root.addLayout(token_row)

        self.token_table = QTableWidget(0, 3)
        self.token_table.setHorizontalHeaderLabels(["Token", "Regex", "Meaning"])
        self.token_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.token_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.token_table.verticalHeader().setVisible(False)
        self.token_table.horizontalHeader().setStretchLastSection(True)
        self.token_table.setColumnWidth(0, 170)
        self.token_table.setColumnWidth(1, 260)
        self.token_table.setMaximumHeight(150)
        self.token_table.setVisible(False)
        root.addWidget(self.token_table)

        tester_title = QLabel("Regex tester (checks all rows, first match wins)")
        tester_title.setObjectName("DialogLabel")
        root.addWidget(tester_title)

        tester_top = QHBoxLayout()
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("Type sample raw item text to test matching...")
        self.btn_test = QPushButton("Test")
        self.btn_test.clicked.connect(self._run_global_test)
        tester_top.addWidget(self.test_input, 1)
        tester_top.addWidget(self.btn_test)
        root.addLayout(tester_top)

        self.test_result = QPlainTextEdit()
        self.test_result.setReadOnly(True)
        self.test_result.setMaximumHeight(150)
        root.addWidget(self.test_result)

        self._populate_token_table()

        self.load_data()

    _TOKEN_DESCRIPTIONS: Dict[str, str] = {
        "SPC": "Optional whitespace",
        "SPC1": "One or more whitespace characters",
        "LP": "Optional left parenthesis",
        "RP": "Optional right parenthesis",
        "COLOR": "Named channel group: K/C/M/Y",
        "DF_TYPE": "Document feeder variants",
        "SFB_BYPASS": "SFB/BYPASS alternative",
    }

    def _on_item_changed(self, _item: QTableWidgetItem):
        if self._loading:
            return
        self._set_dirty(True)

    def _add_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        id_item = QTableWidgetItem("")
        id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, id_item)
        self.table.setItem(row, 1, QTableWidgetItem(""))
        self.table.setItem(row, 2, QTableWidgetItem(""))
        self._set_dirty(True)

    def _populate_token_table(self):
        self.token_table.setRowCount(0)
        for token, value in BUILTIN_REGEX_TOKENS.items():
            row = self.token_table.rowCount()
            self.token_table.insertRow(row)
            self.token_table.setItem(row, 0, QTableWidgetItem(token))
            self.token_table.setItem(row, 1, QTableWidgetItem(value))
            self.token_table.setItem(
                row,
                2,
                QTableWidgetItem(self._TOKEN_DESCRIPTIONS.get(token, "Built-in helper token")),
            )

    def _toggle_token_table(self):
        show_tokens = not self.token_table.isVisible()
        self.token_table.setVisible(show_tokens)
        self.btn_toggle_tokens.setText("Hide Tokens" if show_tokens else "Show Tokens")

    @staticmethod
    def _normalize_for_match(raw: str) -> str:
        text = (raw or "").strip()
        text = re.sub(r"\s+", " ", text)
        return text.replace("（", "(").replace("）", ")")

    @staticmethod
    def _extract_template_fields(template: str) -> Tuple[Set[str], List[str]]:
        formatter = string.Formatter()
        fields: Set[str] = set()
        invalid_fields: List[str] = []

        for _literal, field_name, _format_spec, _conversion in formatter.parse(template):
            if field_name is None:
                continue
            base_name = field_name.split("!", 1)[0].split(":", 1)[0]
            if not base_name:
                invalid_fields.append("{}")
                continue
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", base_name):
                invalid_fields.append(field_name)
                continue
            fields.add(base_name)

        return fields, invalid_fields

    def _get_row_data(self, row: int) -> Tuple[str, str]:
        pattern = (self.table.item(row, 1).text() if self.table.item(row, 1) else "").strip()
        template = (self.table.item(row, 2).text() if self.table.item(row, 2) else "").strip()
        return pattern, template

    def _delete_selected(self):
        row = self.table.currentRow()
        if row < 0:
            return
        id_text = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
        if id_text.isdigit():
            self._deleted_ids.add(int(id_text))
        self.table.removeRow(row)
        self._set_dirty(True)

    def load_data(self):
        self._loading = True
        self._deleted_ids.clear()
        self.table.setRowCount(0)
        for mapping_id, pattern, template in self._db.get_mappings():
            row = self.table.rowCount()
            self.table.insertRow(row)

            id_item = QTableWidgetItem(str(mapping_id))
            id_item.setFlags(id_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(pattern or ""))
            self.table.setItem(row, 2, QTableWidgetItem(template or ""))

        self._loading = False
        self._set_dirty(False)

    def _validate(self) -> Optional[str]:
        seen_patterns: Set[str] = set()
        for row in range(self.table.rowCount()):
            pattern, template = self._get_row_data(row)
            if not pattern or not template:
                return f"Row {row + 1}: Pattern and Template are required."
            if pattern in seen_patterns:
                return f"Row {row + 1}: Duplicate pattern '{pattern}'."
            seen_patterns.add(pattern)

            expanded_pattern, unknown_tokens, _used_tokens = expand_regex_tokens(pattern)
            if unknown_tokens:
                return f"Row {row + 1}: Unknown regex token(s): {', '.join(unknown_tokens)}"

            try:
                compiled = re.compile(expanded_pattern, re.I)
            except re.error as ex:
                return f"Row {row + 1}: Invalid regex: {ex}"

            template_fields, invalid_fields = self._extract_template_fields(template)
            if invalid_fields:
                return f"Row {row + 1}: Invalid template token(s): {', '.join(invalid_fields)}"

            missing_fields = sorted(template_fields - set(compiled.groupindex.keys()))
            if missing_fields:
                return (
                    f"Row {row + 1}: Template token(s) not found in regex named groups: "
                    f"{', '.join(missing_fields)}"
                )

            try:
                template.format(**{name: "x" for name in compiled.groupindex.keys()})
            except (KeyError, ValueError) as ex:
                return f"Row {row + 1}: Invalid template format: {ex}"
        return None

    def _run_global_test(self):
        sample_raw = (self.test_input.text() or "").strip()
        if not sample_raw:
            self.test_result.setPlainText("Enter sample text to test.")
            return

        sample = self._normalize_for_match(sample_raw)
        invalid_rows: List[str] = []
        matched_rows: List[List[str]] = []

        for row in range(self.table.rowCount()):
            pattern, template = self._get_row_data(row)
            if not pattern or not template:
                continue

            expanded_pattern, unknown_tokens, _used_tokens = expand_regex_tokens(pattern)
            if unknown_tokens:
                invalid_rows.append(f"Row {row + 1}: unknown token(s): {', '.join(unknown_tokens)}")
                continue

            try:
                compiled = re.compile(expanded_pattern, re.I)
            except re.error as ex:
                invalid_rows.append(f"Row {row + 1}: invalid regex: {ex}")
                continue

            match = compiled.match(sample)
            if not match:
                continue

            try:
                output = template.format(**match.groupdict())
            except (KeyError, ValueError) as ex:
                invalid_rows.append(f"Row {row + 1}: invalid template: {ex}")
                continue

            group_data = match.groupdict()
            groups_text = ", ".join(f"{k}={v}" for k, v in sorted(group_data.items())) or "(none)"
            matched_rows.append(
                [
                    f"Matched row: {row + 1}",
                    f"Pattern: {pattern}",
                    f"Expanded: {expanded_pattern}",
                    f"Groups: {groups_text}",
                    f"Output: {output}",
                ]
            )

        if matched_rows:
            lines = [
                f"Input: {sample}",
                f"Total matches: {len(matched_rows)}",
                "Runtime behavior: first match wins (row order).",
                "",
            ]
            for idx, result_lines in enumerate(matched_rows, start=1):
                header = f"Match {idx}"
                if idx == 1:
                    header += " (runtime-effective)"
                lines.append(header)
                lines.extend(result_lines)
                if idx != len(matched_rows):
                    lines.append("")

            if invalid_rows:
                lines.append("")
                lines.append("Skipped invalid rows:")
                lines.extend(invalid_rows[:8])
                if len(invalid_rows) > 8:
                    lines.append(f"... and {len(invalid_rows) - 8} more")

            self.test_result.setPlainText("\n".join(lines))
            return

        lines = [f"Input: {sample}", "No mapping matched."]
        if invalid_rows:
            lines.append("")
            lines.append("Skipped invalid rows:")
            lines.extend(invalid_rows[:8])
            if len(invalid_rows) > 8:
                lines.append(f"... and {len(invalid_rows) - 8} more")
        self.test_result.setPlainText("\n".join(lines))

    def save_changes(self):
        err = self._validate()
        if err:
            CustomMessageBox.warn(self, "Validation Error", err, self._icon_dir)
            return

        existing: Dict[int, Tuple[str, str]] = {}
        for mapping_id, pattern, template in self._db.get_mappings():
            existing[int(mapping_id)] = (pattern, template)

        try:
            for mapping_id in self._deleted_ids:
                self._db.delete_mapping(mapping_id)

            for row in range(self.table.rowCount()):
                id_text = (self.table.item(row, 0).text() if self.table.item(row, 0) else "").strip()
                pattern, template = self._get_row_data(row)

                if id_text.isdigit():
                    mapping_id = int(id_text)
                    if existing.get(mapping_id) != (pattern, template):
                        self._db.update_mapping(mapping_id, pattern, template)
                else:
                    self._db.add_mapping(pattern, template)

            reload_mappings_cache()
            KitLinkRule.clear_cache()
            UnitGroupingRule.clear_cache()
            self.load_data()
        except Exception as ex:
            CustomMessageBox.warn(self, "Save Failed", str(ex), self._icon_dir)


class ModelsTab(_EditorTabBase):
    def __init__(self, db: CatalogDB, icon_dir: str, parent=None):
        super().__init__(icon_dir, parent)
        self._db = db
        self._loading = False
        self._deleted_originals: Set[str] = set()

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Models and linked PM Units"), 1)
        self.btn_add = QPushButton("Add")
        self.btn_remove = QPushButton("Delete")
        self.btn_save = QPushButton("Save")
        self.btn_discard = QPushButton("Discard")
        self.btn_add.clicked.connect(self._add_model)
        self.btn_remove.clicked.connect(self._delete_model)
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_discard.clicked.connect(self.load_data)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_discard)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.model_table = QTableWidget(0, 2)
        self.model_table.setHorizontalHeaderLabels(["Original", "Model"])
        self.model_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.model_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.model_table.verticalHeader().setVisible(False)
        self.model_table.setColumnHidden(0, True)
        self.model_table.horizontalHeader().setStretchLastSection(True)
        self.model_table.currentCellChanged.connect(self._on_model_selected)
        self.model_table.itemChanged.connect(self._on_model_changed)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.addWidget(QLabel("Units linked to selected model"))
        self.unit_checks = QListWidget()
        self.unit_checks.itemChanged.connect(self._on_units_changed)
        right_l.addWidget(self.unit_checks, 1)

        splitter.addWidget(self.model_table)
        splitter.addWidget(right)
        splitter.setSizes([420, 520])
        root.addWidget(splitter, 1)

        self.load_data()

    def _current_row(self) -> int:
        return self.model_table.currentRow()

    def _add_model(self):
        row = self.model_table.rowCount()
        self.model_table.insertRow(row)
        orig = QTableWidgetItem("")
        orig.setFlags(orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.model_table.setItem(row, 0, orig)
        editable = QTableWidgetItem("")
        editable.setData(Qt.ItemDataRole.UserRole, set())
        self.model_table.setItem(row, 1, editable)
        self.model_table.setCurrentCell(row, 1)
        self._set_dirty(True)

    def _delete_model(self):
        row = self._current_row()
        if row < 0:
            return
        original = (self.model_table.item(row, 0).text() if self.model_table.item(row, 0) else "").strip()
        if original:
            self._deleted_originals.add(original)
        self.model_table.removeRow(row)
        self._set_dirty(True)

    def _on_model_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 1:
            return
        item.setText((item.text() or "").upper().strip())
        self._set_dirty(True)

    def _on_model_selected(self, *_args):
        self._populate_unit_checks_for_selection()

    def _get_row_units(self, row: int) -> Set[str]:
        if row < 0:
            return set()
        cell = self.model_table.item(row, 1)
        if not cell:
            return set()
        data = cell.data(Qt.ItemDataRole.UserRole)
        return set(data) if isinstance(data, set) else set()

    def _set_row_units(self, row: int, units: Set[str]):
        if row < 0:
            return
        cell = self.model_table.item(row, 1)
        if not cell:
            return
        cell.setData(Qt.ItemDataRole.UserRole, set(units))

    def _populate_unit_checks_for_selection(self):
        self.unit_checks.blockSignals(True)
        self.unit_checks.clear()

        row = self._current_row()
        if row < 0:
            self.unit_checks.blockSignals(False)
            return

        selected = self._get_row_units(row)
        all_units = self._db.get_all_units()
        for unit in all_units:
            item = QListWidgetItem(unit)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if unit in selected else Qt.CheckState.Unchecked)
            self.unit_checks.addItem(item)

        self.unit_checks.blockSignals(False)

    def refresh_available_units(self):
        all_units = set(self._db.get_all_units())

        self._loading = True
        try:
            for row in range(self.model_table.rowCount()):
                linked = self._get_row_units(row)
                filtered = linked & all_units
                if filtered != linked:
                    self._set_row_units(row, filtered)
        finally:
            self._loading = False

        self._populate_unit_checks_for_selection()

    def _on_units_changed(self, _item: QListWidgetItem):
        row = self._current_row()
        if row < 0:
            return
        selected: Set[str] = set()
        for i in range(self.unit_checks.count()):
            itm = self.unit_checks.item(i)
            if itm.checkState() == Qt.CheckState.Checked:
                selected.add(itm.text())
        self._set_row_units(row, selected)
        self._set_dirty(True)

    def load_data(self):
        self._loading = True
        self._deleted_originals.clear()
        self.model_table.setRowCount(0)

        for model_name in self._db.get_all_models():
            row = self.model_table.rowCount()
            self.model_table.insertRow(row)

            orig = QTableWidgetItem(model_name)
            orig.setFlags(orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name = QTableWidgetItem(model_name)
            name.setData(Qt.ItemDataRole.UserRole, set(self._db.get_units_for_model(model_name)))
            self.model_table.setItem(row, 0, orig)
            self.model_table.setItem(row, 1, name)

        if self.model_table.rowCount() > 0:
            self.model_table.setCurrentCell(0, 1)
        self._loading = False
        self._populate_unit_checks_for_selection()
        self._set_dirty(False)

    def _validate(self) -> Optional[str]:
        seen: Set[str] = set()
        for row in range(self.model_table.rowCount()):
            model = (self.model_table.item(row, 1).text() if self.model_table.item(row, 1) else "").upper().strip()
            if not model:
                return f"Row {row + 1}: Model name is required."
            if model in seen:
                return f"Row {row + 1}: Duplicate model name '{model}'."
            seen.add(model)
        return None

    def save_changes(self):
        err = self._validate()
        if err:
            CustomMessageBox.warn(self, "Validation Error", err, self._icon_dir)
            return

        try:
            for original in sorted(self._deleted_originals):
                self._db.delete_model(original)

            for row in range(self.model_table.rowCount()):
                original = (self.model_table.item(row, 0).text() if self.model_table.item(row, 0) else "").upper().strip()
                current = (self.model_table.item(row, 1).text() if self.model_table.item(row, 1) else "").upper().strip()
                units = sorted(self._get_row_units(row))

                if not original:
                    self._db.add_model(current)
                elif original != current:
                    self._db.update_model(original, current)

                self._db.replace_units_for_model(current, units)

            KitLinkRule.clear_cache()
            self.load_data()
        except Exception as ex:
            CustomMessageBox.warn(self, "Save Failed", str(ex), self._icon_dir)


class UnitsTab(_EditorTabBase):
    def __init__(self, db: CatalogDB, icon_dir: str, parent=None):
        super().__init__(icon_dir, parent)
        self._db = db
        self._loading = False
        self._deleted_originals: Set[str] = set()
        self._available_canon_items: Set[str] = set()

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("PM Units and Canon Items"), 1)
        self.btn_add = QPushButton("Add")
        self.btn_remove = QPushButton("Delete")
        self.btn_save = QPushButton("Save")
        self.btn_discard = QPushButton("Discard")
        self.btn_add.clicked.connect(self._add_unit)
        self.btn_remove.clicked.connect(self._delete_unit)
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_discard.clicked.connect(self.load_data)
        top.addWidget(self.btn_add)
        top.addWidget(self.btn_remove)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_discard)
        root.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.unit_table = QTableWidget(0, 2)
        self.unit_table.setHorizontalHeaderLabels(["Original", "PM Unit"])
        self.unit_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.unit_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.unit_table.verticalHeader().setVisible(False)
        self.unit_table.setColumnHidden(0, True)
        self.unit_table.horizontalHeader().setStretchLastSection(True)
        self.unit_table.currentCellChanged.connect(self._on_unit_selected)
        self.unit_table.itemChanged.connect(self._on_unit_changed)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.addWidget(QLabel("Canon items in selected unit"))
        self.item_checks = QListWidget()
        self.item_checks.itemChanged.connect(self._on_items_changed)
        right_l.addWidget(self.item_checks, 1)

        splitter.addWidget(self.unit_table)
        splitter.addWidget(right)
        splitter.setSizes([420, 520])
        root.addWidget(splitter, 1)

        self.load_data()

    def _current_row(self) -> int:
        return self.unit_table.currentRow()

    def _add_unit(self):
        row = self.unit_table.rowCount()
        self.unit_table.insertRow(row)
        orig = QTableWidgetItem("")
        orig.setFlags(orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.unit_table.setItem(row, 0, orig)
        name = QTableWidgetItem("")
        name.setData(Qt.ItemDataRole.UserRole, set())
        self.unit_table.setItem(row, 1, name)
        self.unit_table.setCurrentCell(row, 1)
        self._set_dirty(True)

    def _delete_unit(self):
        row = self._current_row()
        if row < 0:
            return
        original = (self.unit_table.item(row, 0).text() if self.unit_table.item(row, 0) else "").strip()
        if original:
            self._deleted_originals.add(original)
        self.unit_table.removeRow(row)
        self._set_dirty(True)

    def _on_unit_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 1:
            return
        item.setText((item.text() or "").strip())
        self._set_dirty(True)

    def _get_row_items(self, row: int) -> Set[str]:
        if row < 0:
            return set()
        cell = self.unit_table.item(row, 1)
        if not cell:
            return set()
        data = cell.data(Qt.ItemDataRole.UserRole)
        return set(data) if isinstance(data, set) else set()

    def _set_row_items(self, row: int, items: Set[str]):
        if row < 0:
            return
        cell = self.unit_table.item(row, 1)
        if not cell:
            return
        cell.setData(Qt.ItemDataRole.UserRole, set(items))

    def _on_unit_selected(self, *_args):
        self._populate_item_checks_for_selection()

    def _load_available_canon_items(self):
        self._available_canon_items = set(self._db.get_available_canon_items())

    @staticmethod
    def _sort_canon_items(items: Set[str]) -> List[str]:
        return sorted(items, key=lambda value: (value.upper(), value))

    def _populate_item_checks_for_selection(self):
        self.item_checks.blockSignals(True)
        self.item_checks.clear()

        row = self._current_row()
        if row < 0:
            self.item_checks.blockSignals(False)
            return

        selected = self._get_row_items(row)
        stale_selected = selected - self._available_canon_items

        for value in self._sort_canon_items(self._available_canon_items):
            item = QListWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value in selected else Qt.CheckState.Unchecked)
            self.item_checks.addItem(item)

        for value in self._sort_canon_items(stale_selected):
            item = QListWidgetItem(f"{value} (not in Canon Mappings)")
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.item_checks.addItem(item)

        self.item_checks.blockSignals(False)

    def _on_items_changed(self, _item: QListWidgetItem):
        if self._loading:
            return
        row = self._current_row()
        if row < 0:
            return
        selected: Set[str] = set()
        for i in range(self.item_checks.count()):
            item = self.item_checks.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                if value:
                    selected.add(value)
        self._set_row_items(row, selected)
        self._set_dirty(True)

    def refresh_available_canon_items(self):
        self._load_available_canon_items()
        self._populate_item_checks_for_selection()

    def load_data(self):
        self._loading = True
        self._deleted_originals.clear()
        self._load_available_canon_items()
        self.unit_table.setRowCount(0)

        for unit_name in self._db.get_all_units():
            row = self.unit_table.rowCount()
            self.unit_table.insertRow(row)

            orig = QTableWidgetItem(unit_name)
            orig.setFlags(orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name = QTableWidgetItem(unit_name)
            name.setData(Qt.ItemDataRole.UserRole, set(self._db.get_items_for_unit(unit_name)))
            self.unit_table.setItem(row, 0, orig)
            self.unit_table.setItem(row, 1, name)

        if self.unit_table.rowCount() > 0:
            self.unit_table.setCurrentCell(0, 1)
        self._loading = False
        self._populate_item_checks_for_selection()
        self._set_dirty(False)

    def _validate(self) -> Optional[str]:
        seen: Set[str] = set()
        for row in range(self.unit_table.rowCount()):
            unit = (self.unit_table.item(row, 1).text() if self.unit_table.item(row, 1) else "").strip()
            if not unit:
                return f"Row {row + 1}: PM Unit name is required."
            if unit in seen:
                return f"Row {row + 1}: Duplicate PM Unit '{unit}'."
            seen.add(unit)

            missing_items = self._get_row_items(row) - self._available_canon_items
            if missing_items:
                preview = ", ".join(self._sort_canon_items(missing_items)[:5])
                if len(missing_items) > 5:
                    preview += f", and {len(missing_items) - 5} more"
                return f"Row {row + 1}: Canon item(s) not found in Canon Mappings: {preview}."
        return None

    def save_changes(self):
        self._load_available_canon_items()
        err = self._validate()
        if err:
            CustomMessageBox.warn(self, "Validation Error", err, self._icon_dir)
            return

        try:
            for original in sorted(self._deleted_originals):
                self._db.delete_unit(original)

            for row in range(self.unit_table.rowCount()):
                original = (self.unit_table.item(row, 0).text() if self.unit_table.item(row, 0) else "").strip()
                current = (self.unit_table.item(row, 1).text() if self.unit_table.item(row, 1) else "").strip()
                items = sorted(self._get_row_items(row))

                if not original:
                    self._db.add_unit(current)
                elif original != current:
                    self._db.update_unit(original, current)

                self._db.replace_items_for_unit(current, items)

            KitLinkRule.clear_cache()
            UnitGroupingRule.clear_cache()
            self.load_data()
        except Exception as ex:
            CustomMessageBox.warn(self, "Save Failed", str(ex), self._icon_dir)


class PerColorUnitsTab(_EditorTabBase):
    def __init__(self, db: CatalogDB, icon_dir: str, parent=None):
        super().__init__(icon_dir, parent)
        self._db = db
        self._loading = False
        self._original_values: Set[str] = set()
        self._selected_values: Set[str] = set()
        self._available_units: Set[str] = set()

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("Color PM units counted once per due color")
        title.setObjectName("DialogLabel")
        top.addWidget(title, 1)
        self.btn_save = QPushButton("Save")
        self.btn_discard = QPushButton("Discard")
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_discard.clicked.connect(self.load_data)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_discard)
        root.addLayout(top)

        helper = QLabel(
            "Use this for color-specific PM units. If several canon items for the same color are due, "
            "PmGen counts that PM unit once for that color, not once per item. "
            "K/C/M/Y means black, cyan, magenta, and yellow."
        )
        helper.setObjectName("DialogLabel")
        helper.setWordWrap(True)
        root.addWidget(helper)

        self.unit_checks = QListWidget()
        self.unit_checks.itemChanged.connect(self._on_unit_check_changed)
        root.addWidget(self.unit_checks, 1)

        self.load_data()

    @staticmethod
    def _sort_units(units: Set[str]) -> List[str]:
        return sorted(units, key=lambda value: (value.upper(), value))

    def _load_available_units(self):
        self._available_units = set(self._db.get_all_units())

    def _populate_unit_checks(self):
        self.unit_checks.blockSignals(True)
        self.unit_checks.clear()

        stale_values = self._selected_values - self._available_units

        for value in self._sort_units(self._available_units):
            item = QListWidgetItem(value)
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value in self._selected_values else Qt.CheckState.Unchecked)
            self.unit_checks.addItem(item)

        for value in self._sort_units(stale_values):
            item = QListWidgetItem(f"{value} (not in PM Units)")
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.unit_checks.addItem(item)

        self.unit_checks.blockSignals(False)

    def _on_unit_check_changed(self, _item: QListWidgetItem):
        if self._loading:
            return
        self._selected_values = self._current_values()
        self._set_dirty(True)

    def load_data(self):
        self._loading = True
        self._load_available_units()
        values = self._db.get_per_color_units()
        self._original_values = set(values)
        self._selected_values = set(values)
        self._populate_unit_checks()
        self._loading = False
        self._set_dirty(False)

    def _current_values(self) -> Set[str]:
        out: Set[str] = set()
        for i in range(self.unit_checks.count()):
            item = self.unit_checks.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                if value:
                    out.add(value)
        return out

    def refresh_available_units(self):
        self._selected_values = self._current_values() if self.is_dirty else set(self._original_values)
        self._load_available_units()
        self._populate_unit_checks()

    def _validate(self) -> Optional[str]:
        missing_units = self._current_values() - self._available_units
        if missing_units:
            preview = ", ".join(self._sort_units(missing_units)[:5])
            if len(missing_units) > 5:
                preview += f", and {len(missing_units) - 5} more"
            return f"PM Unit(s) not found in PM Units: {preview}."
        return None

    def save_changes(self):
        self._load_available_units()
        err = self._validate()
        if err:
            CustomMessageBox.warn(self, "Validation Error", err, self._icon_dir)
            return

        current = self._current_values()

        try:
            for removed in sorted(self._original_values - current):
                self._db.remove_per_color_unit(removed)
            for added in sorted(current - self._original_values):
                self._db.add_per_color_unit(added)
            UnitGroupingRule.clear_cache()
            self.load_data()
        except Exception as ex:
            CustomMessageBox.warn(self, "Save Failed", str(ex), self._icon_dir)


class QtyOverridesTab(_EditorTabBase):
    def __init__(self, db: CatalogDB, icon_dir: str, parent=None):
        super().__init__(icon_dir, parent)
        self._db = db
        self._loading = False
        self._original: Dict[str, int] = {}
        self._selected_overrides: Dict[str, int] = {}
        self._available_units: Set[str] = set()

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("PM Unit fixed quantity overrides"), 1)
        self.btn_save = QPushButton("Save")
        self.btn_discard = QPushButton("Discard")
        self.btn_save.clicked.connect(self.save_changes)
        self.btn_discard.clicked.connect(self.load_data)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_discard)
        root.addLayout(top)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Override", "PM Unit", "Quantity"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 420)
        self.table.setColumnWidth(2, 120)
        self.table.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.table, 1)

        self.load_data()

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        if item.column() == 2:
            txt = (item.text() or "").strip()
            if txt and not txt.isdigit():
                item.setText("0")
        current = self._current_values()
        if current is not None:
            self._selected_overrides = dict(current)
        self._set_dirty(True)

    @staticmethod
    def _sort_units(units: Set[str]) -> List[str]:
        return sorted(units, key=lambda value: (value.upper(), value))

    def _load_available_units(self):
        self._available_units = set(self._db.get_all_units())

    def _insert_override_row(self, unit_name: str, quantity: int, checked: bool, stale: bool = False):
        row = self.table.rowCount()
        self.table.insertRow(row)

        override_item = QTableWidgetItem("")
        override_item.setData(Qt.ItemDataRole.UserRole, unit_name)
        override_item.setFlags((override_item.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
        override_item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.table.setItem(row, 0, override_item)

        label = f"{unit_name} (not in PM Units)" if stale else unit_name
        unit_item = QTableWidgetItem(label)
        unit_item.setData(Qt.ItemDataRole.UserRole, unit_name)
        unit_item.setFlags(unit_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 1, unit_item)

        qty_item = QTableWidgetItem(str(quantity))
        self.table.setItem(row, 2, qty_item)

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        stale_units = set(self._selected_overrides.keys()) - self._available_units
        for unit_name in self._sort_units(self._available_units):
            quantity = self._selected_overrides.get(unit_name, 1)
            self._insert_override_row(unit_name, quantity, unit_name in self._selected_overrides)

        for unit_name in self._sort_units(stale_units):
            quantity = self._selected_overrides.get(unit_name, 1)
            self._insert_override_row(unit_name, quantity, True, stale=True)

        self.table.blockSignals(False)

    def load_data(self):
        self._loading = True
        self._load_available_units()
        overrides = self._db.get_qty_overrides()
        self._original = dict(overrides)
        self._selected_overrides = dict(overrides)
        self._populate_table()
        self._loading = False
        self._set_dirty(False)

    def _current_values(self) -> Optional[Dict[str, int]]:
        values: Dict[str, int] = {}
        for row in range(self.table.rowCount()):
            override_item = self.table.item(row, 0)
            if not override_item or override_item.checkState() != Qt.CheckState.Checked:
                continue
            unit = str(override_item.data(Qt.ItemDataRole.UserRole) or "").strip()
            qty_text = (self.table.item(row, 2).text() if self.table.item(row, 2) else "").strip()
            if not unit:
                return None
            if not qty_text.isdigit():
                return None
            qty = int(qty_text)
            if qty < 0:
                return None
            values[unit] = qty
        return values

    def refresh_available_units(self):
        if self.is_dirty:
            current = self._current_values()
            if current is None:
                return
            self._selected_overrides = dict(current)
        else:
            self._selected_overrides = dict(self._original)
        self._load_available_units()
        self._populate_table()

    def _validate(self) -> Optional[str]:
        current = self._current_values()
        if current is None:
            return "Checked rows need a numeric quantity."

        missing_units = set(current.keys()) - self._available_units
        if missing_units:
            preview = ", ".join(self._sort_units(missing_units)[:5])
            if len(missing_units) > 5:
                preview += f", and {len(missing_units) - 5} more"
            return f"PM Unit(s) not found in PM Units: {preview}."

        return None

    def save_changes(self):
        self._load_available_units()
        err = self._validate()
        if err:
            CustomMessageBox.warn(self, "Validation Error", err, self._icon_dir)
            return

        current = self._current_values() or {}

        try:
            for removed in sorted(set(self._original.keys()) - set(current.keys())):
                self._db.delete_qty_override(removed)
            for unit, qty in current.items():
                if self._original.get(unit) != qty:
                    self._db.set_qty_override(unit, qty)
            self.load_data()
        except Exception as ex:
            CustomMessageBox.warn(self, "Save Failed", str(ex), self._icon_dir)


class CatalogEditorWindow(WindowResizeMixin, QMainWindow):
    def __init__(self, icon_dir: str, parent=None):
        super().__init__(parent)
        self._icon_dir = icon_dir
        self._db = CatalogDB()
        self._rs = ResizeState()

        self.setWindowTitle("Catalog Editor")
        self.resize(1200, 760)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setMouseTracking(True)

        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        layout.setSpacing(0)

        top_bar = build_frameless_top_bar(
            self,
            WindowControlSpec(
                title="Catalog Editor",
                icon_dir=self._icon_dir,
                on_minimize=self.showMinimized,
                on_toggle_fullscreen=self._toggle_fullscreen,
                on_close=self._confirm_close,
            ),
        )
        top_bar.setProperty("rounded", True)
        layout.addWidget(top_bar, 0)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_MD)

        header_row = QHBoxLayout()
        self.header = QLabel("Edit models, PM units, canon mappings, per-color units, and quantity overrides", content)
        self.header.setObjectName("DialogLabel")
        self.header.setProperty("class", "headline-sm")
        header_row.addWidget(self.header, 1)

        self.btn_save_all = QPushButton("Save All", content)
        self.btn_save_all.setProperty("class", "primary")
        self.btn_save_all.setEnabled(False)
        self.btn_save_all.clicked.connect(self.save_all_changes)
        header_row.addWidget(self.btn_save_all)
        content_layout.addLayout(header_row)

        self.dependency_hint = QLabel("", content)
        self.dependency_hint.setObjectName("DialogLabel")
        self.dependency_hint.setProperty("class", "warning-banner")
        self.dependency_hint.setWordWrap(True)
        self.dependency_hint.setVisible(False)
        content_layout.addWidget(self.dependency_hint)

        self.tabs = QTabWidget(content)
        self.tabs.setObjectName("MainTabs")
        self._tab_base_titles: Dict[_EditorTabBase, str] = {}

        self.tab_canon = CanonMappingsTab(self._db, self._icon_dir, self)
        self.tab_models = ModelsTab(self._db, self._icon_dir, self)
        self.tab_units = UnitsTab(self._db, self._icon_dir, self)
        self.tab_per_color = PerColorUnitsTab(self._db, self._icon_dir, self)
        self.tab_qty = QtyOverridesTab(self._db, self._icon_dir, self)

        self.tabs.addTab(self.tab_models, "Models")
        self.tabs.addTab(self.tab_units, "PM Units")
        self.tabs.addTab(self.tab_canon, "Canon Mappings")
        per_color_idx = self.tabs.addTab(self.tab_per_color, "Per Color Units")
        self.tabs.addTab(self.tab_qty, "Quantity Overrides")
        self.tabs.setTabToolTip(
            per_color_idx,
            "Prevents double-counting color-specific PM units when several items for the same color are due.",
        )
        self._register_dirty_tab_markers()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self.tabs, 1)

        layout.addWidget(content, 1)

        self.setCentralWidget(central)

        # Apply initial window corner rounding from saved preference
        self.apply_window_roundness()

    def _toggle_fullscreen(self, checked: bool):
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _confirm_close(self):
        self.close()

    def _editor_tabs(self) -> List[_EditorTabBase]:
        return [
            self.tab_models,
            self.tab_units,
            self.tab_canon,
            self.tab_per_color,
            self.tab_qty,
        ]

    def _save_all_order(self) -> List[_EditorTabBase]:
        return [
            self.tab_canon,
            self.tab_units,
            self.tab_models,
            self.tab_per_color,
            self.tab_qty,
        ]

    def _register_dirty_tab_markers(self):
        for tab in self._editor_tabs():
            index = self.tabs.indexOf(tab)
            if index < 0:
                continue
            self._tab_base_titles[tab] = self.tabs.tabText(index)
            tab.dirty_changed.connect(lambda _dirty, tab=tab: self._update_tab_dirty_marker(tab))
            self._update_tab_dirty_marker(tab)
        self._update_save_all_enabled()
        self._update_dependency_hint()

    def _update_tab_dirty_marker(self, tab: _EditorTabBase):
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        base_title = self._tab_base_titles.get(tab, self.tabs.tabText(index).rstrip(" *"))
        self.tabs.setTabText(index, f"{base_title} *" if tab.is_dirty else base_title)
        self._update_save_all_enabled()
        self._update_dependency_hint()

    def _update_save_all_enabled(self):
        self.btn_save_all.setEnabled(self._any_dirty())

    def _update_dependency_hint(self):
        has_unsaved_changes = self._any_dirty()
        self.dependency_hint.setText(
            "Save changes to make updated catalog data available across all Catalog Editor tabs."
            if has_unsaved_changes
            else ""
        )
        self.dependency_hint.setVisible(has_unsaved_changes)

    def save_all_changes(self):
        for tab in self._save_all_order():
            if not tab.is_dirty:
                continue

            tab.save_changes()

            if tab.is_dirty:
                index = self.tabs.indexOf(tab)
                if index >= 0:
                    self.tabs.setCurrentIndex(index)
                self._update_save_all_enabled()
                self._update_dependency_hint()
                return

        self._update_save_all_enabled()
        self._update_dependency_hint()

    def _on_tab_changed(self, index: int):
        if self.tabs.widget(index) is self.tab_models:
            self.tab_models.refresh_available_units()
        elif self.tabs.widget(index) is self.tab_units:
            self.tab_units.refresh_available_canon_items()
        elif self.tabs.widget(index) is self.tab_per_color:
            self.tab_per_color.refresh_available_units()
        elif self.tabs.widget(index) is self.tab_qty:
            self.tab_qty.refresh_available_units()

    def _any_dirty(self) -> bool:
        return any(
            tab.is_dirty
            for tab in [
                self.tab_canon,
                self.tab_models,
                self.tab_units,
                self.tab_per_color,
                self.tab_qty,
            ]
        )

    def closeEvent(self, event):
        if self._any_dirty():
            role = CustomMessageBox.confirm(
                self,
                "Unsaved Changes",
                "You have unsaved changes in the Catalog Editor. Close anyway?",
                self._icon_dir,
            )
            if role != "ok":
                event.ignore()
                return
        super().closeEvent(event)

