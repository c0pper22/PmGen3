from __future__ import annotations
import sys, os, re
import shutil
import requests
import logging
from typing import Dict
from collections import deque
from datetime import datetime
from PyQt6.QtCore import (
    Qt, QSize, QPoint, QRect, QEvent, QRegularExpression,
    QCoreApplication, QSettings, QThread, pyqtSlot, QTimer, pyqtSignal,
    QSortFilterProxyModel, QModelIndex, QObject
)
from PyQt6.QtGui import (
    QAction, QIcon, QCursor, QRegularExpressionValidator, QKeySequence, 
    QShortcut, QTextCursor 
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QPlainTextEdit,
    QToolBar, QSizePolicy, QToolButton, QHBoxLayout, QLabel, QMenu,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QSlider, 
    QSpinBox, QDoubleSpinBox, QFileDialog, QProgressBar, QCompleter,
    QTabWidget, QTableView, QHeaderView, QSplitter, QTabBar, QGridLayout,
    QProgressDialog, QTableWidget, QTableWidgetItem, QAbstractItemView
)

# Imports from our new split files
from pmgen.ui.bulk_model import BulkQueueModel
from pmgen.system.wrappers import safe_slot
from .theme import SPACING_LG, SPACING_MD, apply_static_theme
from .theme import (
    RADIUS_LG, CORNER_ROUNDNESS_KEY, CORNER_ROUNDNESS_DEFAULT,
    _corner_scale, _scaled_radius,
)
from .components import (
    DragRegion, TitleDragLabel, FramelessDialog, CustomMessageBox, ResizeState, LoadingDialog
)
from .highlighter import OutputHighlighter
from .workers import BulkConfig, BulkRunner, SingleReportWorker
from pmgen.io.db_access import CatalogDB
from pmgen.io.http_client import get_customer_map_after_login
from pmgen.updater.updater import UpdateWorker, perform_restart, CURRENT_VERSION
from .inventory import InventoryTab
from .factory import UIFactory
from .catalog_editor import CatalogEditorWindow
from .pages import DashboardTabs, InventoryPage, SingleReportPage
from .shell import WindowResizeMixin, resolve_icon_dir


SERVICE_NAME = "PmGen"

# Constants
BORDER_WIDTH = 8
BULK_TOPN_KEY = "bulk/top_n"
BULK_DIR_KEY  = "bulk/out_dir"
BULK_POOL_KEY = "bulk/pool_size"
BULK_BLACKLIST_KEY = "bulk/blacklist"
BULK_MACHINE_FILTER_KEY = "bulk/machine_filter"

# =============================================================================
#  NEW CLASS: BulkSortFilterProxyModel
#  Handles filtering (Search) and custom sorting for the Bulk Table
# =============================================================================
class BulkSortFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def filterAcceptsRow(self, source_row, source_parent):
        """
        Filters rows based on the search text.
        Checks Serial, Model, Customer, and Machine State.
        """
        pattern = self.filterRegularExpression().pattern()
        if not pattern:
            return True
            
        model = self.sourceModel()
        
        # Helper to get string data from a specific column in the source model
        def get_col_str(col_idx):
            idx = model.index(source_row, col_idx, source_parent)
            return str(model.data(idx) or "").lower()

        # Visual Mapping: 1=Serial, 2=Model, 3=Customer, 4=Machine State
        serial = get_col_str(1)
        model_name = get_col_str(2)
        customer = get_col_str(3)
        machine_status = get_col_str(4)
        
        p = pattern.lower()
        return (p in serial) or (p in model_name) or (p in customer) or (p in machine_status)

    def lessThan(self, left: QModelIndex, right: QModelIndex):
        left_data = self.sourceModel().data(left)
        right_data = self.sourceModel().data(right)
        
        col = left.column()
        status_col = self.sourceModel().status_col
        result_col = self.sourceModel().result_col
        
        # --- Sorting Logic for Status ---
        if col == status_col:
            def status_priority(val):
                if val == "Done": return 0
                if val == "Failed": return 1
                if val == "Filtered": return 2
                if val == "Queued": return 3
                return 4
            return status_priority(left_data) < status_priority(right_data)
            
        # --- Sorting Logic for Result (Percentages) ---
        if col == result_col:
            def get_val(val):
                s_val = str(val).strip()
                if "%" in s_val:
                    try: 
                        return float(s_val.replace('%', ''))
                    except ValueError: 
                        return -1.0
                
                if not s_val or s_val in ["—", "..."]:
                    return -2.0
                    
                return s_val.lower()
            
            l_v = get_val(left_data)
            r_v = get_val(right_data)
            
            # If both are floats (percentages or blanks mapped to negative numbers)
            if isinstance(l_v, float) and isinstance(r_v, float):
                return l_v < r_v
            
            # If one is a float and one is text, sort the string as "greater" so it falls to the bottom
            if isinstance(l_v, float) and isinstance(r_v, str):
                return True
            if isinstance(l_v, str) and isinstance(r_v, float):
                return False

            # Default fallback
            return str(l_v) < str(r_v)

        # --- Default String Sort ---
        return str(left_data).lower() < str(right_data).lower()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and index.column() == 0:
            return str(index.row() + 1)
        
        return super().data(index, role)

# =============================================================================
#  CLASS: BulkRunTab
#  Encapsulates a single bulk run (UI + Logic + Thread)
# =============================================================================
class BulkRunTab(QWidget):
    """
    A self-contained tab for a single bulk processing job.
    Owms its own model, view, and worker thread.
    """
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
        life_basis = rk.get("life_basis", "page")
        threshold_enabled = bool(rk.get("threshold_enabled", False))

        unpack_max_enabled = bool(rk.get("unpack_max_enabled", False))
        unpack_max_months = int(rk.get("unpack_max_months", 0) or 0)
        unpack_min_enabled = bool(rk.get("unpack_min_enabled", False))
        unpack_min_months = int(rk.get("unpack_min_months", 0) or 0)

        lines = [
            "[Info] Bulk job settings:",
            f"  - top_n: {cfg.top_n}",
            f"  - pool_size: {cfg.pool_size}",
            f"  - generate_pdfs: {cfg.generate_pdfs}",
            f"  - machine_filter: {cfg.machine_filter}",
            f"  - out_dir: {cfg.out_dir or '(not set)'}",
            f"  - show_all: {cfg.show_all}",
            f"  - threshold_enabled: {threshold_enabled}",
            f"  - threshold: {float(threshold) * 100:.1f}%",
            f"  - life_basis: {str(life_basis).upper()}",
            f"  - blacklist_count: {len(cfg.blacklist or [])}",
            f"  - unpack_max_filter: {unpack_max_enabled} ({unpack_max_months} months)",
            f"  - unpack_min_filter: {unpack_min_enabled} ({unpack_min_months} months)",
            f"  - custom_08_name: {cfg.custom_08_name or '(disabled)'}",
            f"  - custom_08_code: {cfg.custom_08_code}",
            f"  - customer_map_count: {len(self.customer_map or {})}",
        ]
        for line in lines:
            self._log(line)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- Top Bar: Status, Progress, Search, Export, Stop ---
        top_bar = QHBoxLayout()
        
        self.status_label = QLabel("Ready")
        self.status_label.setProperty("class", "status-chip")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)

        # Search Bar
        self.search_bar = QLineEdit()
        self.search_bar.setObjectName("BulkSearch")
        self.search_bar.setPlaceholderText("Search serial, model, customer, state...")
        self.search_bar.setClearButtonEnabled(True)
        self.search_bar.setFixedWidth(200)
        self.search_bar.textChanged.connect(self._on_search_changed)

        # Export Button
        self.btn_export = QPushButton("Export")
        self.btn_export.setObjectName("BulkExportBtn")
        self.btn_export.setFixedHeight(24)
        self.btn_export.clicked.connect(self._export_to_excel)

        # Stop Button
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setObjectName("BulkStopBtn")
        self.btn_stop.setFixedHeight(24)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_stop.setEnabled(False) # Enabled when running

        top_bar.addWidget(self.status_label)
        top_bar.addWidget(self.progress_bar, 1)
        top_bar.addWidget(self.search_bar) 
        top_bar.addWidget(self.btn_export) # Add Export Here
        top_bar.addWidget(self.btn_stop)

        layout.addLayout(top_bar)

        # --- Splitter: Table & Logs ---
        splitter = QSplitter(Qt.Orientation.Vertical)
        
        # 1. The Table & Models
        self.view = QTableView()
        
        # Create base model
        self.model = BulkQueueModel(custom_08_name=self.config.custom_08_name, custom_05_name=self.config.custom_05_name)
        
        # Create Proxy Model for Sorting/Filtering
        self.proxy_model = BulkSortFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.model)
        
        # Assign Proxy to View
        self.view.setModel(self.proxy_model)
        
        self.view.setSortingEnabled(True)
        self.view.setColumnWidth(2, 160)
        self.view.setColumnWidth(3, 300)
        self.view.setColumnWidth(4, 120)
        header = self.view.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._on_context_menu)
        
        splitter.addWidget(self.view)

        # 2. Local Log Window (so user sees errors for *this* run)
        self.log_editor = QPlainTextEdit()
        self.log_editor.setObjectName("MainEditor")
        self.log_editor.setReadOnly(True)
        self.log_editor.setMaximumBlockCount(1000)
        self.log_editor.setPlaceholderText("Run logs will appear here...")
        splitter.addWidget(self.log_editor)
        
        # Set initial sizes (Table gets most space)
        splitter.setSizes([400, 50])
        
        layout.addWidget(splitter, 1)

    def start(self):
        if self._is_running: return
        
        self.model.clear()
        self.log_editor.clear()
        self.btn_stop.setEnabled(True)
        self.status_label.setText("Initializing...")
        self._log_run_settings()
        
        # Create Thread & Runner
        self._thread = QThread()
        self._runner = BulkRunner(self.config, **self.runner_kwargs)
        self._runner.moveToThread(self._thread)

        # Connect Signals
        self._thread.started.connect(self._runner.run)
        
        self._runner.progress.connect(self._on_progress_text)
        self._runner.progress_value.connect(self._on_progress_value)
        self._runner.item_updated.connect(self._on_item_updated)
        self._runner.finished.connect(self._on_finished)
        
        # Cleanup signals
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
        """Updates the proxy filter regex when search bar text changes."""
        regex = QRegularExpression(re.escape(text), QRegularExpression.PatternOption.CaseInsensitiveOption)
        self.proxy_model.setFilterRegularExpression(regex)

    @safe_slot
    def _on_context_menu(self, pos):
        # Get index from View (This is a Proxy Index)
        proxy_index = self.view.indexAt(pos)
        if not proxy_index.isValid(): return
        
        # Map to Source Index to get the correct row for internal data
        source_index = self.proxy_model.mapToSource(proxy_index)
        
        # Use source index row to get data from the underlying model
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
        """Exports the current view (respecting filters/sorting) to an Excel file."""
        import pandas as pd
        
        if self.proxy_model.rowCount() == 0:
            self._log("[Info] Table is empty, nothing to export.")
            return

        # Prompt the user for where to save the file
        file_path, filter_used = QFileDialog.getSaveFileName(
            self, 
            "Export Table", 
            os.path.join(self.config.out_dir, "Bulk_Report_Export.xlsx"), 
            "Excel Files (*.xlsx);;CSV Files (*.csv)"
        )

        if not file_path:
            return  # User canceled

        self._log(f"[Info] Exporting table to {file_path}...")

        try:
            # 1. Grab headers dynamically
            headers = [
                self.model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
                for i in range(self.proxy_model.columnCount())
            ]

            # 2. Iterate over the proxy model (this guarantees we capture the exact current state of the UI)
            data = []
            for row in range(self.proxy_model.rowCount()):
                row_data = []
                for col in range(self.proxy_model.columnCount()):
                    idx = self.proxy_model.index(row, col)
                    val = self.proxy_model.data(idx, Qt.ItemDataRole.DisplayRole)
                    row_data.append(val)
                data.append(row_data)

            # 3. Create DataFrame and export
            df = pd.DataFrame(data, columns=headers)
            
            if file_path.endswith('.csv'):
                df.to_csv(file_path, index=False)
            else:
                # Engine 'openpyxl' is required for .xlsx
                df.to_excel(file_path, index=False, engine='openpyxl')
            
            self._log(f"[Success] Export complete: {file_path}")
            
        except ImportError:
            self._log("[Error] Export failed: Please ensure 'pandas' and 'openpyxl' are installed (pip install pandas openpyxl).")
        except Exception as e:
            self._log(f"[Error] Failed to export table: {str(e)}")

    # --- Worker Slots ---
    @pyqtSlot(str)
    def _on_progress_text(self, text):
        self._log(text)
        if text.startswith("[Bulk]"):
            clean = text.replace("[Bulk]", "").strip()
            self.status_label.setText(clean)
        elif text.startswith("[Info]"):
            clean = text.replace("[Info]", "").strip()
            self.status_label.setText(clean)

    @pyqtSlot(int, int)
    def _on_progress_value(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    @pyqtSlot(str, str, str, str, str, str, str, str)
    def _on_item_updated(self, serial, status, result, model, unpack_date, custom08_val, custom05_val, machine_status):
        c_name = self.customer_map.get(str(serial).strip().upper(), "")
        found = False
        for r in range(self.model.rowCount()):
            if self.model.get_serial_at(r) == serial:
                self.model.update_status(serial, status, result, model, unpack_date, customer=c_name, custom08_val=custom08_val, custom05_val=custom05_val, machine_status=machine_status)
                found = True
                break
        
        if not found:
            self.model.add_item(serial, model, customer=c_name, machine_status=machine_status)
            self.model.update_status(serial, status, result, model, unpack_date, customer=c_name, custom08_val=custom08_val, custom05_val=custom05_val, machine_status=machine_status)
            
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


# Compatibility exports for callers that import these classes from this module.
from .bulk_run import BulkRunTab, BulkSortFilterProxyModel


# =============================================================================
#  MAIN WINDOW
# =============================================================================

BULK_SETTINGS_TOOLTIPS = {
    "top_n": "Number of PDF reports to generate. Only the top N serials ranked by usage percentage are included. Final Reports will be affected.",
    "pool_size": "Number of parallel report generators. Higher can be faster but uses more CPU, and can also encounter memory thrashing and other perfomance issues when set too high. Recommended: 4-8 for most users.",
    "machine_filter": "Choose which serials to process: active, inactive, or both.",
    "custom_08_name": "Optional label for an extra tracking column (e.g. Total Pages). Leave empty to disable.",
    "custom_08_code": "Numeric 08 field code stored in the PM report for this custom column.",
    "custom_08_sub": "Optional sub-code filter. Matches rows with matching SUB value (0 also matches empty sub).",
    "custom_05_name": "Optional label for a 05 adjustment tracking column. Leave empty to disable.",
    "custom_05_code": "Numeric 05 adjustment field code to look up for this custom column.",
    "custom_05_sub": "Optional sub-code filter. Matches rows with matching SUB value (0 also matches empty sub).",
    "generate_pdfs": "When checked, generates downloadable PDF reports alongside the terminal output.",
    "output_dir": "Folder where generated PDF reports and output files are saved.",
    "blacklist": "Serial numbers to skip during processing. Use Add/Remove to manage the list. Supports glob-style wildcards (e.g. ABC*).",
    "unpack_min_age": "Skip serials unpacked more recently than this many months ago.",
    "unpack_max_age": "Skip serials unpacked more than this many months ago.",
}

class _AutoLoginWorker(QObject):
    """Performs auto-login HTTP requests on a background thread."""
    finished = pyqtSignal()
    succeeded = pyqtSignal(object, str)  # (session, username)
    failed = pyqtSignal(str)            # error message

    def __init__(self, username: str, parent=None):
        super().__init__(parent)
        self._username = username

    @pyqtSlot()
    def run(self):
        try:
            from pmgen.io import http_client as hc
            sess = requests.Session()
            hc.login(sess)
            self.succeeded.emit(sess, self._username)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            self.finished.emit()


class MainWindow(WindowResizeMixin, QMainWindow):
    # ---- PM settings Keys ----
    THRESH_KEY = "pm/due_threshold"
    THRESH_ENABLED_KEY = "pm/due_threshold_enabled"
    LIFE_BASIS_KEY = "pm/life_basis"
    COLORIZED_KEY = "ui/colorized_output"
    SHOW_ALL_KEY = "ui/show_all_items"
    ALERTS_ENABLED_KEY = "ui/alerts_enabled"
    CORNER_ROUNDNESS_KEY = "ui/corner_roundness"

    BULK_UNPACK_KEY_ENABLE = "bulk/unpack_filter_enabled"
    BULK_UNPACK_KEY_EXTRA  = "bulk/unpack_extra_months"

    # ---- Auth prefs Keys ----
    AUTH_REMEMBER_KEY = "auth/remember"
    AUTH_USERNAME_KEY = "auth/username"
    HISTORY_KEY = "recent_serials"
    MAX_HISTORY = 25

    sig_start_download = pyqtSignal(str)
    sig_start_extract = pyqtSignal(str)

    customerMap: Dict[str, str] = {}

    def __init__(self, theme_manager=None):
        super().__init__()
        self.theme_manager = theme_manager
        self._rs = ResizeState()
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "pmgen.ico")
        self.setWindowIcon(QIcon(icon_path))

        self.setWindowTitle("PmGen")
        self.resize(1200, 720)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        if getattr(sys, 'frozen', False):
                import glob
                current_dir = os.path.dirname(sys.executable)
                # Look for any file containing ".old."
                for p in glob.glob(os.path.join(current_dir, "*.old*")):
                    try:
                        if os.path.isdir(p):
                            shutil.rmtree(p)
                        else:
                            os.remove(p)
                    except OSError:
                        pass
        
        self._icon_dir = resolve_icon_dir()

        # Auth UI state
        self._signed_in: bool = False
        self._current_user: str = ""
        self._auto_login_attempted: bool = False
        self._session = None
        self._catalog_editor_window: CatalogEditorWindow | None = None

        # Global tracking + event filter
        app = QApplication.instance()
        app.installEventFilter(self)
        self.setMouseTracking(True)

        central = QWidget()
        self.setCentralWidget(central)
        central.setMouseTracking(True)
        
        self._vbox = QVBoxLayout(central)
        self._vbox.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_LG)
        self._vbox.setSpacing(0)

        self.tabs = DashboardTabs()
        self.tabs.tabCloseRequested.connect(self._on_tab_close_requested)
        self._vbox.addWidget(self.tabs)

        ui_factory = UIFactory(self._icon_dir)
        self.tab_home = SingleReportPage(self, self._icon_dir, self)
        self._apply_colorized_highlighter()
        self.tabs.add_pinned_tab(self.tab_home, "Single")

        self.tab_inventory_page = InventoryPage(self, self._icon_dir, self)
        self.tabs.add_pinned_tab(self.tab_inventory_page, "Inventory")

        self.toolbar = ui_factory.create_toolbar(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)

        # UPDATER STATE
        self._update_thread: QThread | None = None
        self._update_worker: UpdateWorker | None = None
        self._update_silent_mode = False

        # Shortcuts
        clear_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        clear_shortcut.activated.connect(self._clear_output_window)
        generate_shortcut = QShortcut(QKeySequence("Return"), self)
        generate_shortcut.activated.connect(self._on_generate_clicked)

        self._update_auth_ui()
        QTimer.singleShot(500, self._attempt_auto_login)

        QTimer.singleShot(1500, lambda: self._start_update_check(silent=True))

        # Apply initial window corner rounding from saved preference
        self.apply_window_roundness(self._get_corner_roundness())

    # =========================================================================
    #  Tab Management
    # =========================================================================
    
    def _on_tab_close_requested(self, index):
        widget = self.tabs.widget(index)
        
        if widget in {self.tab_home, self.tab_tools, self.tab_inventory_page}:
            return
            
        if isinstance(widget, BulkRunTab):
            if widget._is_running:
                res = CustomMessageBox.confirm(
                    self, "Job Running", 
                    "This bulk job is still running.\nAre you sure you want to stop and close it?", 
                    self._icon_dir
                )
                if res != "ok": return
                widget.stop()
                # Defer removal until the thread actually finishes
                widget.finished.connect(lambda w=widget: self._cleanup_bulk_tab(w))
                return
            
        self._safe_remove_tab(index)

    def _safe_remove_tab(self, index):
        widget = self.tabs.widget(index)
        if widget is not None:
            self.tabs.removeTab(index)
            widget.deleteLater()

    def _cleanup_bulk_tab(self, widget):
        idx = self.tabs.indexOf(widget)
        if idx >= 0:
            self.tabs.removeTab(idx)
        widget.deleteLater()

    # =========================================================================
    #  Settings Management
    # =========================================================================
    
    def _get_alerts_enabled(self) -> bool:
        return bool(QSettings().value(self.ALERTS_ENABLED_KEY, True, bool))

    def _set_alerts_enabled(self, on: bool):
        QSettings().setValue(self.ALERTS_ENABLED_KEY, bool(on))

    def _get_unpack_filter_enabled(self) -> bool:
        return bool(QSettings().value(self.BULK_UNPACK_KEY_ENABLE, False, bool))

    def _get_unpack_extra_months(self) -> int:
        try: v = int(QSettings().value(self.BULK_UNPACK_KEY_EXTRA, 0, int))
        except: v = 0
        return max(0, min(120, v))

    def _get_bulk_config(self) -> BulkConfig:
        if hasattr(self, "_bulk_config_cache"):
            return self._bulk_config_cache
        s = QSettings()
        top_n = int(s.value(BULK_TOPN_KEY, 25, int))
        out   = s.value(BULK_DIR_KEY, "", str)
        pool  = int(s.value(BULK_POOL_KEY, 4, int))
        bl_raw = s.value(BULK_BLACKLIST_KEY, "", str) or ""
        bl = [line.strip().upper() for line in re.split(r"[,\n]+", bl_raw) if line.strip()]
        
        c_name = s.value("bulk/custom_08_name", "", str)
        try: c_code = int(s.value("bulk/custom_08_code", 0, int))
        except: c_code = 0
        try: c_sub = int(s.value("bulk/custom_08_sub", 0, int))
        except: c_sub = 0
        c05_name = s.value("bulk/custom_05_name", "", str)
        try: c05_code = int(s.value("bulk/custom_05_code", 0, int))
        except: c05_code = 0
        try: c05_sub = int(s.value("bulk/custom_05_sub", 0, int))
        except: c05_sub = 0
        
        gen_pdfs = bool(s.value("bulk/generate_pdfs", True, bool))
        machine_filter = s.value(BULK_MACHINE_FILTER_KEY, "both", str)

        return BulkConfig(
            top_n=max(1, min(9999, top_n)), 
            out_dir=out, 
            pool_size=max(1, min(16, pool)), 
            blacklist=bl, 
            custom_08_name=c_name, 
            custom_08_code=c_code,
            custom_08_sub=c_sub,
            custom_05_name=c05_name,
            custom_05_code=c05_code,
            custom_05_sub=c05_sub,
            generate_pdfs=gen_pdfs,
            machine_filter=machine_filter
        )

    def _save_bulk_config(self, cfg: BulkConfig):
        self._bulk_config_cache = cfg
        s = QSettings()
        s.setValue(BULK_TOPN_KEY, int(cfg.top_n))
        s.setValue(BULK_DIR_KEY, cfg.out_dir or "")
        s.setValue(BULK_POOL_KEY, int(cfg.pool_size))
        s.setValue(BULK_BLACKLIST_KEY, "\n".join(cfg.blacklist or []))
        s.setValue("bulk/custom_08_name", cfg.custom_08_name)
        s.setValue("bulk/custom_08_code", cfg.custom_08_code)
        s.setValue("bulk/custom_08_sub", cfg.custom_08_sub)
        s.setValue("bulk/custom_05_name", cfg.custom_05_name)
        s.setValue("bulk/custom_05_code", cfg.custom_05_code)
        s.setValue("bulk/custom_05_sub", cfg.custom_05_sub)
        s.setValue("bulk/generate_pdfs", bool(cfg.generate_pdfs))
        s.setValue(BULK_MACHINE_FILTER_KEY, cfg.machine_filter)
        s.sync()

    def _get_show_all(self) -> bool:
        return bool(QSettings().value(self.SHOW_ALL_KEY, False, bool))

    def _set_show_all(self, on: bool):
        QSettings().setValue(self.SHOW_ALL_KEY, bool(on))

    def _get_colorized(self) -> bool:
        return bool(QSettings().value(self.COLORIZED_KEY, True, bool))

    def _set_colorized(self, on: bool):
        QSettings().setValue(self.COLORIZED_KEY, bool(on))

    def _get_threshold(self) -> float:
        try: v = float(QSettings().value(self.THRESH_KEY, 0.80, float))
        except: v = 0.80
        return max(0.0, min(1.0, v))

    def _set_threshold(self, v: float):
        QSettings().setValue(self.THRESH_KEY, float(v))

    def _get_threshold_enabled(self) -> bool:
        return bool(QSettings().value(self.THRESH_ENABLED_KEY, False, bool))

    def _set_threshold_enabled(self, on: bool):
        QSettings().setValue(self.THRESH_ENABLED_KEY, bool(on))
        self._update_threshold_button()

    def _get_life_basis(self) -> str:
        v = (QSettings().value(self.LIFE_BASIS_KEY, "page", str) or "page").lower()
        return "drive" if v.startswith("d") else "page"

    def _set_life_basis(self, v: str):
        QSettings().setValue(self.LIFE_BASIS_KEY, (v or "page").lower())

    def _get_corner_roundness(self) -> int:
        try:
            v = int(QSettings().value(self.CORNER_ROUNDNESS_KEY, 50, int))
        except (TypeError, ValueError):
            v = 50
        return max(0, min(100, v))

    def _set_corner_roundness(self, value: int):
        QSettings().setValue(self.CORNER_ROUNDNESS_KEY, max(0, min(100, int(value))))

    def _load_id_history(self):
        h = QSettings().value(self.HISTORY_KEY, [], list)
        if not isinstance(h, list):
            h = list(h)

        cleaned: list[str] = []
        seen = set()
        for raw in h:
            if not isinstance(raw, str):
                continue
            serial = raw.strip().upper()
            if not serial or serial in seen:
                continue
            seen.add(serial)
            cleaned.append(serial)
            if len(cleaned) >= self.MAX_HISTORY:
                break

        self._set_history(cleaned)

    def _save_id_history(self):
        QSettings().setValue(self.HISTORY_KEY, [self._id_combo.itemText(i) for i in range(self._id_combo.count())])

    def _set_history(self, items: list[str]):
        self._id_combo.clear()
        for it in items: self._id_combo.addItem(it)

    def _upsert_id_history(self, serial: str) -> str:
        """Adds a serial to history, keeping newest-first order and a fixed max size."""
        normalized = (serial or "").strip().upper()
        if not normalized:
            return ""

        items = [normalized]
        seen = {normalized}

        for i in range(self._id_combo.count()):
            existing = (self._id_combo.itemText(i) or "").strip().upper()
            if not existing or existing in seen:
                continue
            seen.add(existing)
            items.append(existing)
            if len(items) >= self.MAX_HISTORY:
                break

        self._set_history(items)
        self._id_combo.setEditText(normalized)
        self._save_id_history()
        return normalized

    def _reset_update_thread(self):
            """
            Clears the python reference to the thread so we don't 
            accidentally access a deleted C++ object later.
            """
            self._update_thread = None
            self._update_worker = None

    def _start_update_check(self, silent=False):
        """
        silent=True: Used on startup (only notify if update FOUND).
        silent=False: Used on button click (notify if up-to-date or error).
        """
        # SAFE CHECK: Ensure we don't access a deleted thread
        if self._update_thread is not None:
            if self._update_thread.isRunning():
                if not silent:
                    self.editor.appendPlainText("[Update] Check already in progress...")
                return

        self._update_silent_mode = silent
        if not silent:
            self.editor.appendPlainText("[Info] Checking for updates...")
        
        self._update_thread = QThread()
        self._update_worker = UpdateWorker()
        self._update_worker.moveToThread(self._update_thread)
        
        self._update_thread.started.connect(self._update_worker.check_updates)
        self._update_worker.check_finished.connect(self._on_check_finished)
        self._update_worker.error_occurred.connect(self._on_update_error)
        self._update_worker.download_progress.connect(self._on_download_progress)
        self._update_worker.download_finished.connect(self._on_download_complete)
        
        self._update_worker.check_finished.connect(self._update_thread.quit)
        self._update_worker.error_occurred.connect(self._update_thread.quit)
        
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.finished.connect(self._reset_update_thread)
        
        self._update_thread.start()

    @pyqtSlot(bool, str, str)
    def _on_check_finished(self, found, version_tag, url):
        self._update_thread.quit() # Stop the check thread
        
        if found:
            res = CustomMessageBox.confirm(
                self, 
                "Update Available", 
                f"New version {version_tag} is available.\nDo you want to update now?", 
                self._icon_dir
            )
            if res == "ok":
                self._start_download(url)
        else:
            if not self._update_silent_mode:
                CustomMessageBox.info(self, "Up to Date", f"You are on the latest version ({CURRENT_VERSION}).", self._icon_dir)

    @pyqtSlot(str)
    def _on_update_error(self, msg):
        self._update_thread.quit()
        if not self._update_silent_mode:
            self.editor.appendPlainText(f"[Update Error] {msg}")
            CustomMessageBox.warn(self, "Update Error", msg, self._icon_dir)

    def _start_download(self, url):
        self.editor.appendPlainText("[Update] Starting download...")
        
        self._dl_thread = QThread()
        self._dl_worker = UpdateWorker()
        self._dl_worker.moveToThread(self._dl_thread)
        
        self.sig_start_download.connect(self._dl_worker.download_update)
        self.sig_start_extract.connect(self._dl_worker.extract_update)
        
        self._dl_worker.download_progress.connect(self._on_download_progress)
        self._dl_worker.extraction_progress.connect(self._on_download_progress)
        
        self._dl_worker.download_finished.connect(self._on_download_complete)
        self._dl_worker.extraction_finished.connect(self._on_extraction_complete)
        self._dl_worker.error_occurred.connect(self._on_update_error)
        
        self._dl_worker.extraction_finished.connect(self._dl_thread.quit)
        self._dl_worker.error_occurred.connect(self._dl_thread.quit)
        self._dl_thread.finished.connect(self._dl_thread.deleteLater)
        
        self._dl_thread.start()

        self._dl_dialog = FramelessDialog(self, "Updating PmGen", self._icon_dir)
        self._dl_bar = QProgressBar(self._dl_dialog)
        self._dl_bar.setObjectName("ProgressBar")
        self._dl_bar.setRange(0, 100)
        self._dl_bar.setValue(0)
        
        self._dl_label = QLabel("Downloading Update...", self._dl_dialog)
        self._dl_label.setObjectName("DialogLabel")

        self._dl_dialog._content_layout.addWidget(self._dl_label)
        self._dl_dialog._content_layout.addWidget(self._dl_bar)
        self._dl_dialog.show()

        self.sig_start_download.emit(url)

    @pyqtSlot(int)
    def _on_download_progress(self, pct):
        """Shared slot for both download and extraction progress."""
        if hasattr(self, "_dl_bar"):
            self._dl_bar.setValue(pct)

    @pyqtSlot(str)
    def _on_download_complete(self, zip_path):
        """Switch UI to Extraction mode and start extraction via signal."""
        if hasattr(self, "_dl_label"):
            self._dl_label.setText("Extracting Files...")
        if hasattr(self, "_dl_bar"):
            self._dl_bar.setValue(0)
            
        self.sig_start_extract.emit(zip_path)

    @pyqtSlot(str, str)
    def _on_extraction_complete(self, zip_path, extract_dir):
        if hasattr(self, "_dl_dialog"):
            self._dl_dialog.close()
        
        perform_restart(zip_path, extract_dir)

    # =========================================================================
    #  Actions & Logic
    # =========================================================================

    def _update_threshold_button(self):
        if not hasattr(self, "_thr_button"):
            return
        enabled = self._get_threshold_enabled()
        if enabled:
            value = self._get_threshold()
            pct = int(value * 100)
            self._thr_button.setText(f"Threshold: {pct}%")
            r, g, b = self._threshold_heat_color(value)
            self._thr_button.setStyleSheet(
                f"QPushButton#ThresholdToggle {{"
                f"  color: #{r:02x}{g:02x}{b:02x};"
                f"  background: rgba({r},{g},{b},31);"
                f"  border-color: rgba({r},{g},{b},102);"
                f"}}"
                f"QPushButton#ThresholdToggle:hover {{"
                f"  background: rgba({r},{g},{b},56);"
                f"  border-color: rgba({r},{g},{b},166);"
                f"}}"
            )
        else:
            self._thr_button.setText("Threshold: 100%")
            self._thr_button.setStyleSheet("")

    def _threshold_heat_color(self, value: float):
        """0.0 → green (#40a02b), 0.5 → yellow (#df8e1d), 1.0 → red (#ba1a1a)."""
        if value <= 0.5:
            t = value / 0.5
            r = int(0x40 + t * (0xdf - 0x40))
            g = int(0xa0 + t * (0x8e - 0xa0))
            b = int(0x2b + t * (0x1d - 0x2b))
        else:
            t = (value - 0.5) / 0.5
            r = int(0xdf + t * (0xba - 0xdf))
            g = int(0x8e + t * (0x1a - 0x8e))
            b = int(0x1d + t * (0x1a - 0x1d))
        return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))

    def _toggle_threshold_enabled(self):
        self._set_threshold_enabled(not self._get_threshold_enabled())
        self._update_threshold_button()

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_thr_button", None) and event.type() == QEvent.Type.Wheel:
            if self._get_threshold_enabled():
                delta = event.angleDelta().y()
                step = 0.05 if delta > 0 else -0.05
                new_val = max(0.0, min(1.0, self._get_threshold() + step))
                self._set_threshold(new_val)
                self._update_threshold_button()
            return True
        return super().eventFilter(obj, event)

    def _update_basis_button(self):
        if hasattr(self, "_basis_button"):
            basis = self._get_life_basis()
            self._basis_button.setText(f"Basis: {basis.upper()}")
            self._basis_button.setProperty("basis", basis)
            self._basis_button.style().unpolish(self._basis_button)
            self._basis_button.style().polish(self._basis_button)

    def _toggle_life_basis(self):
        current = self._get_life_basis()
        new = "drive" if current == "page" else "page"
        self._set_life_basis(new)
        self._update_basis_button()

    def _auto_capitalize(self, text: str):
        le = self._id_combo.lineEdit()
        cursor = le.cursorPosition()
        le.blockSignals(True)
        le.setText(text.upper())
        le.setCursorPosition(cursor)
        le.blockSignals(False)

    def _apply_colorized_highlighter(self):
        if not hasattr(self, "_out_highlighter"): self._out_highlighter = None
        want, have = self._get_colorized(), self._out_highlighter is not None
        if want and not have:
            self._out_highlighter = OutputHighlighter(self.editor.document())
        elif not want and have:
            self._out_highlighter.setDocument(None); self._out_highlighter.deleteLater(); self._out_highlighter = None
            self.editor.setPlainText(self.editor.toPlainText())
    
    @safe_slot
    def _on_generate_clicked(self, *args):
        if getattr(self, '_single_thread', None) is not None and self._single_thread.isRunning():
            return 

        serial = self._upsert_id_history(self._id_combo.currentText())
        if not serial:
            return

        threshold = self._get_threshold()
        life_basis = self._get_life_basis()
        show_all = self._get_show_all()
        threshold_enabled = self._get_threshold_enabled()
        alerts_enabled = self._get_alerts_enabled()
        
        session = self._session
        if not session:
            self.editor.appendPlainText("Error: You must be logged in to generate a report.")
            return

        self.loading_dialog = LoadingDialog(
            parent=self, 
            title="Please Wait", 
            message="Fetching data and generating report...", 
            icon_dir=self._icon_dir
        )
        self.loading_dialog.show()

        self._single_thread = QThread()
        self._single_worker = SingleReportWorker(
            session=session,
            serial=serial,
            threshold=threshold,
            life_basis=life_basis,
            show_all=show_all,
            threshold_enabled=threshold_enabled,
            alerts_enabled=alerts_enabled,
            customer_name=self.customerMap.get(serial, "")
        )
        self._single_worker.moveToThread(self._single_thread)

        self._single_thread.started.connect(self._single_worker.run)
        
        self._single_worker.finished.connect(self._on_single_report_success)
        self._single_worker.error.connect(self._on_single_report_error)
        
        self._single_worker.finished.connect(self._cleanup_single_thread)
        self._single_worker.error.connect(self._cleanup_single_thread)
        
        self._single_thread.finished.connect(self._single_thread.deleteLater)
        self._single_worker.finished.connect(self._single_worker.deleteLater)

        self._single_thread.finished.connect(self._reset_single_thread)

        self._single_thread.start()

    def _on_single_report_success(self, report_text):
        """Called automatically when the background worker succeeds."""
        self.editor.setPlainText(report_text)
        
        if hasattr(self, '_apply_colorized_highlighter'):
             self._apply_colorized_highlighter()

    def _on_single_report_error(self, error_message):
        """Called automatically if the background worker fails."""
        self.editor.setPlainText(error_message)

    def _cleanup_single_thread(self):
        """Closes the loading screen and cleanly stops the thread."""
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            self.loading_dialog.accept()
            
        self._single_thread.quit()

    def _reset_single_thread(self):
        """
        Clears the python reference to the thread so we don't 
        accidentally access a deleted C++ object later.
        """
        self._single_thread = None
        self._single_worker = None

    @safe_slot
    def _start_bulk(self, *args):
        cfg = self._get_bulk_config()
        cfg.show_all = self._get_show_all()
        
        s = QSettings()
        unpack_max_enabled = bool(s.value("bulk/unpack_filter_enabled", False, bool))
        unpack_max_months = int(s.value("bulk/unpack_extra_months", 0, int))
        unpack_min_enabled = bool(s.value("bulk/unpack_min_filter_enabled", False, bool))
        unpack_min_months = int(s.value("bulk/unpack_min_months", 0, int))

        runner_kwargs = {
            "threshold": self._get_threshold(),
            "life_basis": self._get_life_basis(),
            "threshold_enabled": self._get_threshold_enabled(),
            "unpack_max_enabled": unpack_max_enabled,
            "unpack_max_months": unpack_max_months,
            "unpack_min_enabled": unpack_min_enabled,
            "unpack_min_months": unpack_min_months,
            "customer_map": self.customerMap,
        }

        tab = BulkRunTab(cfg, runner_kwargs)
        
        tab.inspect_requested.connect(self._on_bulk_inspect_requested)
        
        title = f"Bulk {datetime.now().strftime('%H:%M')}"
        idx = self.tabs.addTab(tab, title)
        self.tabs.setCurrentIndex(idx)
        
        tab.start()
        
    @pyqtSlot(str)
    def _on_bulk_inspect_requested(self, serial):
        """Called when a Bulk Tab 'Inspect' context menu is clicked."""
        serial = self._upsert_id_history(serial)
        if not serial:
            return
        self.tabs.setCurrentWidget(self.tab_home)
        self._id_combo.setEditText(serial)
        self._on_generate_clicked()

    def _clear_output_window(self): self.editor.clear()

    # =========================================================================
    #  Dialogs
    # =========================================================================
    @safe_slot
    def _open_due_threshold_dialog(self, *args):
        dlg = FramelessDialog(self, "Optional Threshold", self._icon_dir)
        top = QLabel("Items over 100% life are always DUE.\nOptionally enable a lower due threshold.", dlg)
        top.setObjectName("DialogLabel")
        
        enable_cb = QCheckBox("Enable Optional threshold", dlg); enable_cb.setObjectName("DialogCheckbox")
        enable_cb.setChecked(self._get_threshold_enabled())

        slider = QSlider(Qt.Orientation.Horizontal, dlg)
        slider.setObjectName("ThresholdSlider")
        slider.setRange(0, 100); slider.setTickInterval(10); slider.setValue(int(self._get_threshold()*100))

        pct_box = QDoubleSpinBox(dlg); pct_box.setObjectName("DialogInput")
        pct_box.setRange(0.0, 100.0); pct_box.setSuffix("%"); pct_box.setValue(self._get_threshold()*100.0)
        
        slider.setEnabled(enable_cb.isChecked()); pct_box.setEnabled(enable_cb.isChecked())
        
        enable_cb.toggled.connect(lambda c: (self._set_threshold_enabled(c), slider.setEnabled(c), pct_box.setEnabled(c)))
        slider.valueChanged.connect(lambda v: pct_box.setValue(float(v)))
        pct_box.valueChanged.connect(lambda v: slider.setValue(int(v)))

        save_btn = QPushButton("Save", dlg)
        save_btn.clicked.connect(lambda: (self._set_threshold(pct_box.value()/100.0), self._update_threshold_button(), dlg.accept()))

        dlg._content_layout.addWidget(top); dlg._content_layout.addWidget(enable_cb)
        r1 = QHBoxLayout(); r1.addWidget(slider, 1); r1.addWidget(pct_box); dlg._content_layout.addLayout(r1)
        r2 = QHBoxLayout(); r2.addStretch(1); r2.addWidget(save_btn); dlg._content_layout.addLayout(r2)
        dlg.exec()
    
    @safe_slot
    def _open_login_dialog(self, *args):
        dlg = FramelessDialog(self, "Login", self._icon_dir)
        u_in = QLineEdit(dlg); u_in.setObjectName("DialogInput"); u_in.setPlaceholderText("Username")
        if (last_user := QSettings().value(self.AUTH_USERNAME_KEY, "", str)): u_in.setText(last_user)
        p_in = QLineEdit(dlg); p_in.setEchoMode(QLineEdit.EchoMode.Password); p_in.setObjectName("DialogInput"); p_in.setPlaceholderText("Password")
        
        remember = QCheckBox("Stay Logged In", dlg); remember.setObjectName("DialogCheckbox")
        remember.setChecked(bool(QSettings().value(self.AUTH_REMEMBER_KEY, False, bool)))
        
        btn_login = QPushButton("Login", dlg); btn_login.setDefault(True)

        def _do_login():
            u, p = u_in.text().strip(), p_in.text()
            if not u or not p: return

            logging.info(f"Attempting manual login for user: {u}")

            btn_login.setEnabled(False); self.user_label.setText("Signing in…"); self.editor.appendPlainText(f"[Auto-Login] Attempting as {u}…")
            try:
                from pmgen.io import http_client as hc
                hc.save_credentials(u, p)
                sess = requests.Session()
                hc.login(sess)
                QSettings().setValue(self.AUTH_REMEMBER_KEY, remember.isChecked())
                QSettings().setValue(self.AUTH_USERNAME_KEY, u)
                self._session = sess
                self._signed_in = True; self._current_user = u; self._update_auth_ui()
                self.editor.appendPlainText(f"[Auto-Login] {u} — success")
                self.customerMap = get_customer_map_after_login(sess)
                dlg.accept()
            except Exception as e:
                self._signed_in = False; self._current_user = ""; self._update_auth_ui()
                self.editor.appendPlainText(f"[Auto-Login] {u} — failed: {e}")
                CustomMessageBox.warn(self, "Login failed", str(e), self._icon_dir)
            finally: btn_login.setEnabled(True)

        btn_login.clicked.connect(_do_login)
        dlg._content_layout.addWidget(QLabel("Username", dlg)); dlg._content_layout.addWidget(u_in)
        dlg._content_layout.addWidget(QLabel("Password", dlg)); dlg._content_layout.addWidget(p_in)
        row = QHBoxLayout(); row.addWidget(remember); row.addStretch(1); row.addWidget(btn_login)
        dlg._content_layout.addLayout(row); dlg.exec()

    @safe_slot
    def _open_life_basis_dialog(self, *args):
        dlg = FramelessDialog(self, "Life Basis", self._icon_dir)
        lbl = QLabel("Choose counter basis (fallback to other if missing).", dlg); lbl.setObjectName("DialogLabel")
        box = QComboBox(dlg); box.setObjectName("DialogInput"); box.addItems(["Page", "Drive"])
        box.setCurrentIndex(0 if self._get_life_basis() == "page" else 1)
        btn = QPushButton("Save", dlg)
        btn.clicked.connect(lambda: (self._set_life_basis("page" if box.currentIndex()==0 else "drive"), self._update_basis_button(), dlg.accept()))
        dlg._content_layout.addWidget(lbl); dlg._content_layout.addWidget(box)
        r = QHBoxLayout(); r.addStretch(1); r.addWidget(btn); dlg._content_layout.addLayout(r)
        dlg.exec()

    @safe_slot
    def _open_appearance_dialog(self, *args):
        dlg = FramelessDialog(self, "Appearance", self._icon_dir)
        lbl = QLabel("Choose the application color theme and corner roundness.", dlg)
        lbl.setObjectName("DialogLabel")

        btn_theme = QPushButton(dlg)
        btn_theme.setObjectName("ThemeToggleButton")
        btn_theme.setProperty("class", "primary")
        btn_theme.setCheckable(True)

        def _sync_theme_button():
            manager = getattr(self, "theme_manager", None)
            is_dark = bool(getattr(manager, "is_dark", True))
            btn_theme.setChecked(is_dark)
            btn_theme.setText("Switch to Light Mode" if is_dark else "Switch to Dark Mode")

        def _toggle_theme():
            manager = getattr(self, "theme_manager", None)
            if manager is None:
                return
            manager.toggle()
            _sync_theme_button()

        corner_label = QLabel("Corner Roundness", dlg)
        corner_label.setObjectName("DialogLabel")

        corner_slider = QSlider(Qt.Orientation.Horizontal, dlg)
        corner_slider.setObjectName("ThresholdSlider")
        corner_slider.setRange(0, 100)
        corner_slider.setTickInterval(10)

        corner_box = QSpinBox(dlg)
        corner_box.setObjectName("DialogInput")
        corner_box.setRange(0, 100)
        corner_box.setSuffix("%")

        corner_slider.setValue(self._get_corner_roundness())
        corner_box.setValue(self._get_corner_roundness())

        def _apply_corner_roundness(value: int):
            self._set_corner_roundness(value)
            manager = getattr(self, "theme_manager", None)
            if manager is not None:
                manager.reapply()
            self.apply_window_roundness(value)

        btn_theme.clicked.connect(lambda _checked=False: _toggle_theme())
        corner_slider.valueChanged.connect(lambda v: corner_box.setValue(int(v)))
        corner_box.valueChanged.connect(lambda v: corner_slider.setValue(int(v)))
        corner_slider.valueChanged.connect(_apply_corner_roundness)
        _sync_theme_button()

        dlg._content_layout.addWidget(lbl)
        dlg._content_layout.addWidget(btn_theme)
        dlg._content_layout.addWidget(corner_label)
        row_roundness = QHBoxLayout()
        row_roundness.addWidget(corner_slider, 1)
        row_roundness.addWidget(corner_box)
        dlg._content_layout.addLayout(row_roundness)
        row = QHBoxLayout()
        row.addStretch(1)
        dlg._content_layout.addLayout(row)
        dlg.exec()


    @safe_slot
    def _open_bulk_settings(self, *args):
        cfg = self._get_bulk_config()
        s = QSettings()
        dlg = FramelessDialog(self, "Bulk Settings", self._icon_dir)
        dlg.setMinimumSize(980, 700)
        dlg.resize(980, 700)

        def _section(title: str):
            section = QWidget(dlg)
            section.setObjectName("DialogSection")
            section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(12, 10, 12, 12)
            section_layout.setSpacing(8)
            title_label = QLabel(title, section)
            title_label.setObjectName("DialogSectionTitle")
            section_layout.addWidget(title_label)
            return section, section_layout

        def _form_label(text: str, parent: QWidget):
            label = QLabel(text, parent)
            label.setObjectName("DialogFormLabel")
            return label

        def _info_badge(parent: QWidget, key: str) -> QLabel:
            badge = QLabel("\u24d8", parent)
            badge.setToolTip(BULK_SETTINGS_TOOLTIPS.get(key, ""))
            badge.setProperty("class", "muted")
            badge.setCursor(Qt.CursorShape.WhatsThisCursor)
            badge.setFixedWidth(14)
            return badge

        def _info_container(parent: QWidget) -> QWidget:
            """Transparent container for label + info badge rows."""
            w = QWidget(parent)
            w.setProperty("class", "info-row")
            return w

        def _set_field_width(widget, width=140):
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width)
            widget.setMinimumHeight(34)
            return widget

        def _grid_row(grid: QGridLayout, row: int, label: str, widget, parent: QWidget, tooltip_key: str = ""):
            if tooltip_key:
                container = _info_container(parent)
                h = QHBoxLayout(container)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(2)
                h.addWidget(_form_label(label, container))
                h.addWidget(_info_badge(container, tooltip_key))
                h.addStretch(1)
                grid.addWidget(container, row, 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                grid.addWidget(_form_label(label, parent), row, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(widget, row, 1, Qt.AlignmentFlag.AlignRight)
        
        # --- Standard Config ---
        sp_pool = _set_field_width(QSpinBox(dlg), 180); sp_pool.setObjectName("DialogInput"); sp_pool.setRange(1, 16); sp_pool.setValue(cfg.pool_size)
        machine_box = QComboBox(dlg); machine_box.setObjectName("DialogInput")
        for label, value in (("Both", "both"), ("Active", "active"), ("Inactive", "inactive")):
            machine_box.addItem(label, value)
        machine_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        machine_box.setMinimumContentsLength(len("Inactive"))
        machine_box.setMinimumWidth(180)
        machine_box.setMaximumWidth(180)
        machine_box.setMinimumHeight(34)
        machine_box.view().setMinimumWidth(machine_box.minimumWidth())
        machine_box.view().setTextElideMode(Qt.TextElideMode.ElideNone)
        machine_idx = machine_box.findData(cfg.machine_filter)
        machine_box.setCurrentIndex(machine_idx if machine_idx >= 0 else 0)
        cb_gen_pdfs = QCheckBox("Generate PDF Reports", dlg)
        cb_gen_pdfs.setObjectName("DialogCheckbox")
        cb_gen_pdfs.setMinimumHeight(30)
        cb_gen_pdfs.setChecked(cfg.generate_pdfs)
        ed_dir = QLineEdit(cfg.out_dir, dlg); ed_dir.setObjectName("DialogInput")
        ed_dir.setMinimumHeight(34)
        btn_br = QPushButton("Browse", dlg); btn_br.setFixedSize(112, 34); btn_br.clicked.connect(lambda: ed_dir.setText(QFileDialog.getExistingDirectory(self, "Out", cfg.out_dir) or cfg.out_dir))
        
        def toggle_out_dir(checked):
            ed_dir.setEnabled(checked)
            btn_br.setEnabled(checked)
        cb_gen_pdfs.toggled.connect(toggle_out_dir)
        toggle_out_dir(cfg.generate_pdfs)

        sp_top = _set_field_width(QSpinBox(dlg), 96); sp_top.setObjectName("DialogInput")
        sp_top.setRange(1, 9999); sp_top.setValue(cfg.top_n)
        cb_gen_pdfs.toggled.connect(sp_top.setEnabled)
        sp_top.setEnabled(cfg.generate_pdfs)

        bl_table = QTableWidget(0, 1, dlg)
        bl_table.setObjectName("BlacklistTable")
        bl_table.setHorizontalHeaderLabels(["Serial Number"])
        bl_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        bl_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        bl_table.verticalHeader().setVisible(False)
        bl_table.horizontalHeader().setStretchLastSection(True)
        bl_table.setAlternatingRowColors(True)
        bl_table.setMinimumHeight(100)

        # Apply corner roundness directly to header sections (CSS :first/:last cascade
        # is unreliable in Qt for single-column tables)
        corner_strength = int(QSettings().value(CORNER_ROUNDNESS_KEY, CORNER_ROUNDNESS_DEFAULT, int))
        bl_radius = _scaled_radius(RADIUS_LG, _corner_scale(corner_strength))
        bl_table.setStyleSheet(
            f"QHeaderView {{"
            f"  background: transparent;"
            f"  border-top-left-radius: {bl_radius}px;"
            f"  border-top-right-radius: {bl_radius}px;"
            f"}}"
            f"QHeaderView::section {{"
            f"  border-top-left-radius: {bl_radius}px;"
            f"  border-top-right-radius: {bl_radius}px;"
            f"}}"
            f"QTableCornerButton::section {{"
            f"  border-top-left-radius: {bl_radius}px;"
            f"}}"
            f"QTableWidget QLineEdit {{"
            f"  padding: 2px 4px;"
            f"  border: none;"
            f"  border-radius: 0px;"
            f"}}"
        )

        for serial in (cfg.blacklist or []):
            row = bl_table.rowCount()
            bl_table.insertRow(row)
            bl_table.setItem(row, 0, QTableWidgetItem(serial))

        def _add_blacklist_row():
            row = bl_table.rowCount()
            bl_table.insertRow(row)
            bl_table.setItem(row, 0, QTableWidgetItem(""))
            bl_table.editItem(bl_table.item(row, 0))
            bl_table.scrollToBottom()

        def _remove_blacklist_rows():
            rows = sorted({idx.row() for idx in bl_table.selectedIndexes()}, reverse=True)
            for row in rows:
                bl_table.removeRow(row)

        btn_add_bl = QPushButton("+ Add", dlg)
        btn_add_bl.setFixedSize(80, 30)
        btn_add_bl.clicked.connect(_add_blacklist_row)
        btn_rem_bl = QPushButton("\u2212 Remove", dlg)
        btn_rem_bl.setFixedSize(100, 30)
        btn_rem_bl.clicked.connect(_remove_blacklist_rows)
        
        # --- Date Filters (Max Age / Min Age) ---
        
        # 1. Max Age (Existing: "Unpack Filter")
        cb_max_age = QCheckBox("Exclude older than", dlg); cb_max_age.setObjectName("DialogCheckbox"); cb_max_age.setMinimumHeight(30)
        cb_max_age.setChecked(bool(s.value("bulk/unpack_filter_enabled", False, bool)))
        sp_max_age = _set_field_width(QSpinBox(dlg), 96); sp_max_age.setObjectName("DialogInput"); sp_max_age.setRange(0, 120)
        sp_max_age.setValue(int(s.value("bulk/unpack_extra_months", 0, int))) # Reusing existing key
        
        # 2. Min Age (New)
        cb_min_age = QCheckBox("Exclude newer than", dlg); cb_min_age.setObjectName("DialogCheckbox"); cb_min_age.setMinimumHeight(30)
        cb_min_age.setChecked(bool(s.value("bulk/unpack_min_filter_enabled", False, bool)))
        sp_min_age = _set_field_width(QSpinBox(dlg), 96); sp_min_age.setObjectName("DialogInput"); sp_min_age.setRange(0, 120)
        sp_min_age.setValue(int(s.value("bulk/unpack_min_months", 0, int)))

        cb_max_age.toggled.connect(sp_max_age.setEnabled)
        cb_min_age.toggled.connect(sp_min_age.setEnabled)
        sp_max_age.setEnabled(cb_max_age.isChecked())
        sp_min_age.setEnabled(cb_min_age.isChecked())

        btn_save = QPushButton("Save", dlg)
        btn_save.setProperty("class", "primary")
        btn_save.setFixedSize(120, 40)

        # --- Custom 08 Filters ---
        cb_cust_name = QLineEdit(cfg.custom_08_name, dlg); cb_cust_name.setObjectName("DialogInput")
        cb_cust_name.setMinimumHeight(34)
        cb_cust_name.setPlaceholderText("Leave Empty to disable")
        sp_cust_code = _set_field_width(QSpinBox(dlg), 120); sp_cust_code.setObjectName("DialogInput")
        sp_cust_code.setRange(0, 999999); sp_cust_code.setValue(cfg.custom_08_code)
        sp_cust_sub = _set_field_width(QSpinBox(dlg), 120); sp_cust_sub.setObjectName("DialogInput")
        sp_cust_sub.setRange(0, 999999); sp_cust_sub.setValue(cfg.custom_08_sub)

        # --- Custom 05 Filters ---
        cb_cust05_name = QLineEdit(cfg.custom_05_name, dlg); cb_cust05_name.setObjectName("DialogInput")
        cb_cust05_name.setMinimumHeight(34)
        cb_cust05_name.setPlaceholderText("Leave Empty to disable")
        sp_cust05_code = _set_field_width(QSpinBox(dlg), 120); sp_cust05_code.setObjectName("DialogInput")
        sp_cust05_code.setRange(0, 999999); sp_cust05_code.setValue(cfg.custom_05_code)
        sp_cust05_sub = _set_field_width(QSpinBox(dlg), 120); sp_cust05_sub.setObjectName("DialogInput")
        sp_cust05_sub.setRange(0, 999999); sp_cust05_sub.setValue(cfg.custom_05_sub)

        def _save():
            bl = []
            seen = set()
            for r in range(bl_table.rowCount()):
                item = bl_table.item(r, 0)
                if item:
                    val = item.text().strip().upper()
                    if val and val not in seen:
                        bl.append(val)
                        seen.add(val)
            self._save_bulk_config(BulkConfig(
                top_n=sp_top.value(), out_dir=ed_dir.text().strip(), 
                pool_size=sp_pool.value(), blacklist=bl,
                custom_08_name=cb_cust_name.text().strip(), custom_08_code=sp_cust_code.value(),
                custom_08_sub=sp_cust_sub.value(),
                custom_05_name=cb_cust05_name.text().strip(), custom_05_code=sp_cust05_code.value(),
                custom_05_sub=sp_cust05_sub.value(),
                generate_pdfs=cb_gen_pdfs.isChecked(),
                machine_filter=machine_box.currentData() or "both"
            ))
            
            
            # Save Max Age (Existing keys)
            s.setValue("bulk/unpack_filter_enabled", cb_max_age.isChecked())
            s.setValue("bulk/unpack_extra_months", sp_max_age.value())
            
            # Save Min Age (New keys)
            s.setValue("bulk/unpack_min_filter_enabled", cb_min_age.isChecked())
            s.setValue("bulk/unpack_min_months", sp_min_age.value())
            
            dlg.accept()

        btn_save.clicked.connect(_save)

        l = dlg._content_layout
        l.setSpacing(10)

        general_section, general_layout = _section("General")
        general_grid = QGridLayout()
        general_grid.setContentsMargins(0, 0, 0, 0)
        general_grid.setHorizontalSpacing(16)
        general_grid.setVerticalSpacing(8)
        general_grid.setColumnStretch(0, 1)
        _grid_row(general_grid, 0, "Parallel workers", sp_pool, general_section, "pool_size")
        _grid_row(general_grid, 1, "Machine filter", machine_box, general_section, "machine_filter")
        general_layout.addLayout(general_grid)

        custom_section, custom_layout = _section("Custom 08 Tracking")
        custom_grid = QGridLayout()
        custom_grid.setContentsMargins(0, 0, 0, 0)
        custom_grid.setHorizontalSpacing(16)
        custom_grid.setVerticalSpacing(8)
        custom_grid.setColumnStretch(0, 1)
        col_name_row = _info_container(custom_section)
        cnr = QHBoxLayout(col_name_row)
        cnr.setContentsMargins(0, 0, 0, 0)
        cnr.setSpacing(2)
        cnr.addWidget(_form_label("Column name", col_name_row))
        cnr.addWidget(_info_badge(col_name_row, "custom_08_name"))
        cnr.addStretch(1)
        custom_grid.addWidget(col_name_row, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        custom_grid.addWidget(cb_cust_name, 0, 1)
        _grid_row(custom_grid, 1, "08 code", sp_cust_code, custom_section, "custom_08_code")
        _grid_row(custom_grid, 2, "Sub", sp_cust_sub, custom_section, "custom_08_sub")
        custom_layout.addLayout(custom_grid)

        custom05_section, custom05_layout = _section("Custom 05 Tracking")
        custom05_grid = QGridLayout()
        custom05_grid.setContentsMargins(0, 0, 0, 0)
        custom05_grid.setHorizontalSpacing(16)
        custom05_grid.setVerticalSpacing(8)
        custom05_grid.setColumnStretch(0, 1)
        col05_name_row = _info_container(custom05_section)
        c5nr = QHBoxLayout(col05_name_row)
        c5nr.setContentsMargins(0, 0, 0, 0)
        c5nr.setSpacing(2)
        c5nr.addWidget(_form_label("Column name", col05_name_row))
        c5nr.addWidget(_info_badge(col05_name_row, "custom_05_name"))
        c5nr.addStretch(1)
        custom05_grid.addWidget(col05_name_row, 0, 0, Qt.AlignmentFlag.AlignVCenter)
        custom05_grid.addWidget(cb_cust05_name, 0, 1)
        _grid_row(custom05_grid, 1, "05 code", sp_cust05_code, custom05_section, "custom_05_code")
        _grid_row(custom05_grid, 2, "Sub", sp_cust05_sub, custom05_section, "custom_05_sub")
        custom05_layout.addLayout(custom05_grid)

        top_sections = QHBoxLayout()
        top_sections.setContentsMargins(0, 0, 0, 0)
        top_sections.setSpacing(10)
        top_sections.addWidget(general_section, 1)
        top_sections.addWidget(custom_section, 1)
        top_sections.addWidget(custom05_section, 1)
        l.addLayout(top_sections)

        bottom_sections = QHBoxLayout()
        bottom_sections.setContentsMargins(0, 0, 0, 0)
        bottom_sections.setSpacing(10)

        output_section, output_layout = _section("Output")
        pdf_row = _info_container(output_section)
        pr = QHBoxLayout(pdf_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(2)
        pr.addWidget(cb_gen_pdfs)
        pr.addWidget(_info_badge(output_section, "generate_pdfs"))
        pr.addStretch(1)
        output_layout.addWidget(pdf_row)
        reports_row = _info_container(output_section)
        rr = QHBoxLayout(reports_row)
        rr.setContentsMargins(0, 0, 0, 0)
        rr.setSpacing(8)
        rr.addWidget(_form_label("# of Reports", reports_row))
        rr.addWidget(_info_badge(reports_row, "top_n"))
        rr.addStretch(1)
        rr.addWidget(sp_top)
        output_layout.addWidget(reports_row)
        r_dir = QHBoxLayout()
        r_dir.setContentsMargins(0, 0, 0, 0)
        r_dir.setSpacing(8)
        r_dir.addWidget(ed_dir, 1)
        r_dir.addWidget(btn_br)
        od_row = _info_container(output_section)
        odl = QHBoxLayout(od_row)
        odl.setContentsMargins(0, 0, 0, 0)
        odl.setSpacing(2)
        odl.addWidget(_form_label("Output directory", od_row))
        odl.addWidget(_info_badge(od_row, "output_dir"))
        odl.addStretch(1)
        output_layout.addWidget(od_row)
        output_layout.addLayout(r_dir)
        bl_row = _info_container(output_section)
        brl = QHBoxLayout(bl_row)
        brl.setContentsMargins(0, 0, 0, 0)
        brl.setSpacing(2)
        brl.addWidget(_form_label("Blacklist", bl_row))
        brl.addWidget(_info_badge(bl_row, "blacklist"))
        brl.addStretch(1)
        output_layout.addWidget(bl_row)
        output_layout.addWidget(bl_table)
        bl_btn_row = QHBoxLayout()
        bl_btn_row.setContentsMargins(0, 0, 0, 0)
        bl_btn_row.setSpacing(8)
        bl_btn_row.addWidget(btn_add_bl)
        bl_btn_row.addWidget(btn_rem_bl)
        bl_btn_row.addStretch(1)
        output_layout.addLayout(bl_btn_row)
        bottom_sections.addWidget(output_section, 1)

        filters_section, filters_layout = _section("Unpack Date Filters")
        filters_grid = QGridLayout()
        filters_grid.setContentsMargins(0, 0, 0, 0)
        filters_grid.setHorizontalSpacing(8)
        filters_grid.setVerticalSpacing(2)
        filters_grid.setColumnStretch(0, 1)
        min_row = _info_container(filters_section)
        mnr = QHBoxLayout(min_row)
        mnr.setContentsMargins(0, 0, 0, 0)
        mnr.setSpacing(2)
        mnr.addWidget(cb_min_age)
        mnr.addWidget(_info_badge(filters_section, "unpack_min_age"))
        mnr.addStretch(1)
        filters_grid.addWidget(min_row, 0, 0)
        filters_grid.addWidget(sp_min_age, 0, 1)
        filters_grid.addWidget(QLabel("months", filters_section), 0, 2)
        max_row = _info_container(filters_section)
        mxr = QHBoxLayout(max_row)
        mxr.setContentsMargins(0, 0, 0, 0)
        mxr.setSpacing(2)
        mxr.addWidget(cb_max_age)
        mxr.addWidget(_info_badge(filters_section, "unpack_max_age"))
        mxr.addStretch(1)
        filters_grid.addWidget(max_row, 1, 0)
        filters_grid.addWidget(sp_max_age, 1, 1)
        filters_grid.addWidget(QLabel("months", filters_section), 1, 2)
        filters_layout.addLayout(filters_grid)
        bottom_sections.addWidget(filters_section, 0, Qt.AlignmentFlag.AlignTop)
        l.addLayout(bottom_sections)

        r_btn = QHBoxLayout()
        r_btn.addStretch(1)
        r_btn.addWidget(btn_save)
        l.addLayout(r_btn)

        dlg.exec()

    def _show_about(self):
        try:
            models = sorted(CatalogDB().get_all_models())
        except Exception:
            models = []
        txt = f"PmGen\nVersion: {CURRENT_VERSION}\nSupported models: {len(models)}\n—\n"
        # Simple columns
        for i in range(0, len(models), 4): txt += "".join(s.ljust(12) for s in models[i:i+4]) + "\n"
        
        dlg = FramelessDialog(self, "About", self._icon_dir)
        t = QPlainTextEdit(dlg); t.setReadOnly(True); t.setObjectName("MainEditor"); t.setPlainText(txt)
        btn = QPushButton("OK", dlg); btn.clicked.connect(dlg.accept)
        dlg._content_layout.addWidget(t); dlg._content_layout.addWidget(btn)
        dlg.exec()

    @safe_slot
    def _open_catalog_editor(self, *args):
        if self._catalog_editor_window is None:
            self._catalog_editor_window = CatalogEditorWindow(self._icon_dir, self)
            self._catalog_editor_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self._catalog_editor_window.destroyed.connect(lambda *_: setattr(self, "_catalog_editor_window", None))

        self._catalog_editor_window.show()
        self._catalog_editor_window.raise_()
        self._catalog_editor_window.activateWindow()

    # =========================================================================
    #  Auth & Event Logic
    # =========================================================================

    def _attempt_auto_login(self):
        if self._auto_login_attempted or self._signed_in:
            return
        s = QSettings()
        if not bool(s.value(self.AUTH_REMEMBER_KEY, False, bool)):
            self._auto_login_attempted = True
            return
        u = s.value(self.AUTH_USERNAME_KEY, "", str)
        if not u:
            self._auto_login_attempted = True
            return

        self._auto_login_attempted = True
        self.user_label.setText("Signing in…")
        self.editor.appendPlainText(f"[Auto-Login] Attempting as {u}…")

        # Run login on a background thread to avoid blocking the UI
        self._login_thread = QThread()
        self._login_worker = _AutoLoginWorker(u)
        self._login_worker.moveToThread(self._login_thread)

        self._login_thread.started.connect(self._login_worker.run)
        self._login_worker.succeeded.connect(self._on_auto_login_success)
        self._login_worker.failed.connect(self._on_auto_login_failure)
        self._login_worker.finished.connect(self._login_thread.quit)
        self._login_worker.finished.connect(self._login_worker.deleteLater)
        self._login_thread.finished.connect(self._login_thread.deleteLater)
        self._login_thread.start()

    @pyqtSlot(object, str)
    def _on_auto_login_success(self, session, username):
        self._session = session
        self._signed_in = True
        self._current_user = username
        self._update_auth_ui()
        self.editor.appendPlainText(f"[Auto-Login] {username} — success")
        try:
            self.customerMap = get_customer_map_after_login(session)
        except Exception:
            pass

    @pyqtSlot(str)
    def _on_auto_login_failure(self, error_msg):
        self._signed_in = False
        self._current_user = ""
        self._update_auth_ui()
        self.editor.appendPlainText(f"[Auto-Login] — failed: {error_msg}")

    @safe_slot
    def _logout(self, *args):
        logging.info("User requested logout.")
        QSettings().setValue(self.AUTH_REMEMBER_KEY, False); QSettings().setValue(self.AUTH_USERNAME_KEY, "")
        try:
            from pmgen.io import http_client as hc
            if hasattr(hc, "server_side_logout"): hc.server_side_logout()
            if hasattr(hc, "SessionPool"): hc.SessionPool.close_all_pools()
            hc.clear_credentials()
        except: pass
        self._signed_in = False; self._current_user = ""; self._session = None; self._update_auth_ui(); self.editor.appendPlainText("[Info] - Logout Successful")

    def _update_auth_ui(self):
        self.user_label.setText(self._current_user or "(signed in)" if self._signed_in else "Not signed in")

    def _toggle_fullscreen(self, checked: bool): self.showFullScreen() if checked else self.showNormal()

    def _confirm_exit(self):
        if CustomMessageBox.confirm(self, "Exit", "Are you sure you want to exit?", self._icon_dir) == "ok": self.close()

    def closeEvent(self, ev):
        self._save_id_history()
        
        df = self.tab_tools.model.get_dataframe()
        
        if df is not None and not df.empty:
            dlg = CustomMessageBox(
                self, 
                "Active Inventory", 
                "You have items in your inventory.\nWould you like to keep them for your next session or delete them?", 
                self._icon_dir, 
                [("Cancel", "cancel"), ("Delete", "delete"), ("Keep", "keep")]
            )
            dlg.exec()
            
            choice = dlg._clicked_role or "cancel"
            
            if choice == "cancel":
                ev.ignore()
                return
            elif choice == "delete":
                cache_path = self.tab_tools._get_cache_path()
                if os.path.exists(cache_path):
                    try:
                        os.remove(cache_path)
                        logging.info("Inventory cache deleted on exit.")
                    except OSError as e:
                        logging.error(f"Failed to delete inventory cache: {e}")
        super().closeEvent(ev)

