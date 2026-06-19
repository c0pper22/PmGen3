"""Bulk run tab widgets and proxy models for dynamic bulk-job tabs."""

from __future__ import annotations

import os
import re
from typing import Dict

import pandas as pd
from PyQt6.QtCore import QModelIndex, QRegularExpression, QSortFilterProxyModel, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QTextCursor
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from pmgen.system.wrappers import safe_slot
from pmgen.ui.bulk_model import BulkQueueModel
from pmgen.ui.theme import SPACING_MD, SPACING_SM
from pmgen.ui.widgets import configure_table_view, make_card
from pmgen.ui.workers import BulkConfig, BulkRunner


class BulkSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True

        model = self.sourceModel()

        def get_col_str(col_idx):
            idx = model.index(source_row, col_idx, source_parent)
            return str(model.data(idx) or "").lower()

        serial = get_col_str(1)
        model_name = get_col_str(2)
        customer = get_col_str(3)
        machine_status = get_col_str(4)
        query = pattern.lower()
        return query in serial or query in model_name or query in customer or query in machine_status

    def lessThan(self, left: QModelIndex, right: QModelIndex):
        left_data = self.sourceModel().data(left)  # type: ignore[union-attr]
        right_data = self.sourceModel().data(right)  # type: ignore[union-attr]

        col = left.column()
        sm = self.sourceModel()
        status_col = sm.status_col if sm else -1  # type: ignore[union-attr,attr-defined]
        result_col = sm.result_col if sm else -1  # type: ignore[union-attr,attr-defined]

        if col == status_col:
            def status_priority(val):
                if val == "Done":
                    return 0
                if val == "Failed":
                    return 1
                if val == "Filtered":
                    return 2
                if val == "Queued":
                    return 3
                return 4

            return status_priority(left_data) < status_priority(right_data)

        if col == result_col:
            def get_val(val):
                raw = str(val).strip()
                if "%" in raw:
                    try:
                        return float(raw.replace("%", ""))
                    except ValueError:
                        return -1.0
                if not raw or raw in {"—", "..."}:
                    return -2.0
                return raw.lower()

            left_value = get_val(left_data)
            right_value = get_val(right_data)
            if isinstance(left_value, float) and isinstance(right_value, float):
                return left_value < right_value
            if isinstance(left_value, float) and isinstance(right_value, str):
                return True
            if isinstance(left_value, str) and isinstance(right_value, float):
                return False
            return str(left_value) < str(right_value)

        return str(left_data).lower() < str(right_data).lower()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 0:
            return str(index.row() + 1)
        return super().data(index, role)


class BulkRunTab(QWidget):
    inspect_requested = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, config: BulkConfig, runner_kwargs: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.runner_kwargs = dict(runner_kwargs)
        self.customer_map = self._normalize_customer_map(self.runner_kwargs.get("customer_map", {}))
        self.runner_kwargs["customer_map"] = self.customer_map
        self._thread: QThread | None = None
        self._runner: BulkRunner | None = None
        self._is_running = False
        self._setup_ui()

    @staticmethod
    def _normalize_customer_map(customer_map: Dict[str, str]) -> Dict[str, str]:
        return {
            str(serial).strip().upper(): customer_name
            for serial, customer_name in (customer_map or {}).items()
            if str(serial).strip()
        }

    def _log_run_settings(self):
        cfg = self.config
        rk = self.runner_kwargs or {}
        threshold = rk.get("threshold", 0.0)
        lines = [
            "[Info] Bulk job settings:",
            f"  - top_n: {cfg.top_n}",
            f"  - pool_size: {cfg.pool_size}",
            f"  - generate_pdfs: {cfg.generate_pdfs}",
            f"  - machine_filter: {cfg.machine_filter}",
            f"  - out_dir: {cfg.out_dir or '(not set)'}",
            f"  - show_all: {cfg.show_all}",
            f"  - threshold_enabled: {bool(rk.get('threshold_enabled', False))}",
            f"  - threshold: {float(threshold) * 100:.1f}%",
            f"  - life_basis: {str(rk.get('life_basis', 'page')).upper()}",
            f"  - blacklist_count: {len(cfg.blacklist or [])}",
            f"  - unpack_max_filter: {bool(rk.get('unpack_max_enabled', False))} ({int(rk.get('unpack_max_months', 0) or 0)} months)",
            f"  - unpack_min_filter: {bool(rk.get('unpack_min_enabled', False))} ({int(rk.get('unpack_min_months', 0) or 0)} months)",
            f"  - custom_08_name: {cfg.custom_08_name or '(disabled)'}",
            f"  - custom_08_code: {cfg.custom_08_code}",
            f"  - customer_map_count: {len(self.customer_map or {})}",
        ]
        for line in lines:
            self._log(line)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_SM, 0, 0)
        layout.setSpacing(SPACING_MD)

        header_card = make_card(self, "BulkRunHeader")
        header_card.setFixedHeight(56)
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)
        header_layout.setSpacing(SPACING_SM)

        self.status_label = QLabel("Ready", header_card)
        self.status_label.setProperty("class", "status-chip")

        self.progress_bar = QProgressBar(header_card)
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)

        self.search_bar = QLineEdit(header_card)
        self.search_bar.setObjectName("BulkSearch")
        self.search_bar.setPlaceholderText("Search serial, model, customer, state...")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.setFixedWidth(240)
        self.search_bar.textChanged.connect(self._on_search_changed)

        self.btn_export = QPushButton("Export", header_card)
        self.btn_export.setObjectName("BulkExportBtn")
        self.btn_export.setProperty("class", "secondary")
        self.btn_export.setFixedHeight(32)
        self.btn_export.setMinimumWidth(80)
        self.btn_export.clicked.connect(self._export_to_excel)

        self.btn_stop = QPushButton("Stop", header_card)
        self.btn_stop.setObjectName("BulkStopBtn")
        self.btn_stop.setProperty("class", "danger")
        self.btn_stop.setFixedHeight(32)
        self.btn_stop.setMinimumWidth(80)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setEnabled(False)

        header_layout.addWidget(self.status_label)
        header_layout.addWidget(self.progress_bar, 1)
        header_layout.addWidget(self.search_bar)
        header_layout.addWidget(self.btn_export)
        header_layout.addWidget(self.btn_stop)
        layout.addWidget(header_card)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.view = QTableView(splitter)
        self.model = BulkQueueModel(custom_08_name=self.config.custom_08_name, custom_05_name=self.config.custom_05_name)
        self.proxy_model = BulkSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        self.view.setModel(self.proxy_model)
        configure_table_view(self.view, compact=True)
        self.view.setColumnWidth(2, 160)
        self.view.setColumnWidth(3, 300)
        self.view.setColumnWidth(4, 120)
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        splitter.addWidget(self.view)

        self.log_editor = QPlainTextEdit(splitter)
        self.log_editor.setObjectName("MainEditor")
        self.log_editor.setReadOnly(True)
        self.log_editor.setMaximumBlockCount(1000)
        self.log_editor.setPlaceholderText("Run logs will appear here...")
        splitter.addWidget(self.log_editor)
        splitter.setSizes([400, 50])
        layout.addWidget(splitter, 1)

    def start(self):
        if self._is_running:
            return
        self.model.clear()
        self.log_editor.clear()
        self.btn_stop.setEnabled(True)
        self.status_label.setText("Initializing...")
        self._log_run_settings()
        self._thread = QThread()
        self._runner = BulkRunner(self.config, **self.runner_kwargs)
        self._runner.moveToThread(self._thread)
        self._thread.started.connect(self._runner.run)
        self._runner.progress.connect(self._on_progress_text)
        self._runner.progress_value.connect(self._on_progress_value)
        self._runner.item_updated.connect(self._on_item_updated)
        self._runner.finished.connect(self._on_finished)
        self._runner.finished.connect(self._thread.quit)
        self._runner.finished.connect(self._runner.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._on_thread_gone)
        self._thread.start()
        self._is_running = True

    def stop(self):
        if self._is_running and self._thread:
            self._log("[Info] Stop requested... (this may take a moment to finish current tasks)")
            self._thread.requestInterruption()
            self.btn_stop.setEnabled(False)

    def _on_search_changed(self, text):
        regex = QRegularExpression(re.escape(text), QRegularExpression.PatternOption.CaseInsensitiveOption)
        self.proxy_model.setFilterRegularExpression(regex)

    @safe_slot
    def _on_context_menu(self, pos):
        proxy_index = self.view.indexAt(pos)
        if not proxy_index.isValid():
            return
        source_index = self.proxy_model.mapToSource(proxy_index)
        serial = self.model.get_serial_at(source_index.row())
        menu = QMenu(self.view)
        act_inspect = QAction("Inspect / Generate Single Report", self.view)
        act_inspect.triggered.connect(lambda: self.inspect_requested.emit(serial))
        menu.addAction(act_inspect)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _open_folder(self):
        if self.config.out_dir and os.path.exists(self.config.out_dir):
            os.startfile(self.config.out_dir)

    def _export_to_excel(self):
        if self.proxy_model.rowCount() == 0:
            self._log("[Info] Table is empty, nothing to export.")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Table",
            os.path.join(self.config.out_dir, "Bulk_Report_Export.xlsx"),
            "Excel Files (*.xlsx);;CSV Files (*.csv)",
        )
        if not file_path:
            return
        self._log(f"[Info] Exporting table to {file_path}...")
        try:
            headers = [
                self.model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                for i in range(self.proxy_model.columnCount())
            ]
            data = []
            for row in range(self.proxy_model.rowCount()):
                data.append([
                    self.proxy_model.data(self.proxy_model.index(row, col), Qt.ItemDataRole.DisplayRole)
                    for col in range(self.proxy_model.columnCount())
                ])
            df = pd.DataFrame(data, columns=headers)
            if file_path.endswith(".csv"):
                df.to_csv(file_path, index=False)
            else:
                df.to_excel(file_path, index=False, engine="openpyxl")
            self._log(f"[Success] Export complete: {file_path}")
        except ImportError:
            self._log("[Error] Export failed: Please ensure 'pandas' and 'openpyxl' are installed.")
        except Exception as exc:
            self._log(f"[Error] Failed to export table: {exc}")

    @pyqtSlot(str)
    def _on_progress_text(self, text):
        self._log(text)
        if text.startswith("[Bulk]"):
            self.status_label.setText(text.replace("[Bulk]", "").strip())
        elif text.startswith("[Info]"):
            self.status_label.setText(text.replace("[Info]", "").strip())

    @pyqtSlot(int, int)
    def _on_progress_value(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(str, str, str, str, str, str, str, str)
    def _on_item_updated(self, serial, status, result, model, unpack_date, custom08_val, custom05_val, machine_status):
        customer_name = self.customer_map.get(str(serial).strip().upper(), "")
        found = False
        for row in range(self.model.rowCount()):
            if self.model.get_serial_at(row) == serial:
                self.model.update_status(
                    serial,
                    status,
                    result,
                    model,
                    unpack_date,
                    customer=customer_name,
                    custom08_val=custom08_val,
                    custom05_val=custom05_val,
                    machine_status=machine_status,
                )
                found = True
                break
        if not found:
            self.model.add_item(serial, model, customer=customer_name, machine_status=machine_status)
            self.model.update_status(
                serial,
                status,
                result,
                model,
                unpack_date,
                customer=customer_name,
                custom08_val=custom08_val,
                custom05_val=custom05_val,
                machine_status=machine_status,
            )

    @pyqtSlot(str)
    def _on_finished(self, msg):
        self._log(msg)
        self.status_label.setText("Done")
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.view.sortByColumn(self.model.status_col, Qt.SortOrder.AscendingOrder)
        self.btn_stop.setEnabled(False)
        self.finished.emit()

    def _on_thread_gone(self):
        self._thread = None
        self._runner = None
        self._is_running = False

    def _log(self, text):
        self.log_editor.appendPlainText(text)
        self.log_editor.moveCursor(QTextCursor.MoveOperation.End)
