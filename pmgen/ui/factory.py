from __future__ import annotations
import sys
from PyQt6.QtCore import Qt, QRegularExpression
from PyQt6.QtGui import QAction, QRegularExpressionValidator
from PyQt6.QtWidgets import (
    QWidget, QToolBar, QToolButton, 
    QHBoxLayout, QLabel, QMenu, QPushButton, QComboBox, 
    QCompleter
)

from .components import CustomMessageBox
from .shell import WindowControlSpec, build_frameless_top_bar
from .theme import SPACING_MD, SPACING_SM
from pmgen.updater.updater import CURRENT_VERSION

BORDER_WIDTH = 8

class UIFactory:
    """
    Encapsulates the creation of complex UI bars (Toolbar, Secondary Bar)
    to keep MainWindow clean.
    """
    def __init__(self, icon_dir: str):
        self._icon_dir = icon_dir

    def create_toolbar(self, window) -> QToolBar:
        """
        Builds the main top toolbar and assigns necessary actions to the window.
        """
        tb = QToolBar("Window Controls", window)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setMouseTracking(True)

        # --- Settings Menu ---
        settings_btn = QToolButton()
        settings_btn.setObjectName("SettingsBtn")
        settings_btn.setText("Settings ▾")
        settings_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        settings_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        settings_btn.setFixedHeight(36)
        
        settings_menu = QMenu(settings_btn)
        
        window.act_login = QAction("Login", window)
        window.act_login.triggered.connect(window._open_login_dialog)
        
        window.act_logout = QAction("Logout", window)
        window.act_logout.triggered.connect(window._logout)
        
        settings_menu.addAction(window.act_login)
        settings_menu.addAction(window.act_logout)
        
        act_due = QAction("Optional Threshold", window)
        act_due.triggered.connect(window._open_due_threshold_dialog)
        settings_menu.addAction(act_due)
        
        act_basis = QAction("Life Basis", window)
        act_basis.triggered.connect(window._open_life_basis_dialog)
        settings_menu.addAction(act_basis)
        
        act_show_all = QAction("Show All Items", window)
        act_show_all.setCheckable(True)
        act_show_all.setChecked(window._get_show_all())
        act_show_all.toggled.connect(window._set_show_all)
        settings_menu.addAction(act_show_all)
        
        act_color = QAction("Colorized Output", window)
        act_color.setCheckable(True)
        act_color.setChecked(window._get_colorized())
        act_color.toggled.connect(lambda c: (window._set_colorized(c), window._apply_colorized_highlighter()))
        settings_menu.addAction(act_color)

        act_rich = QAction("Rich Report View", window)
        act_rich.setCheckable(True)
        act_rich.setChecked(window._get_report_style() == "widget")
        act_rich.toggled.connect(lambda c: window._set_report_style("widget" if c else "text"))
        settings_menu.addAction(act_rich)

        act_appearance = QAction("Appearance", window)
        act_appearance.triggered.connect(window._open_appearance_dialog)
        settings_menu.addAction(act_appearance)
        
        act_clear = QAction("Clear Output Window", window)
        act_clear.triggered.connect(window._clear_output_window)
        settings_menu.addAction(act_clear)
        
        act_about = QAction("About", window)
        act_about.triggered.connect(window._show_about)
        settings_menu.addAction(act_about)

        act_catalog_editor = QAction("Catalog Editor", window)
        act_catalog_editor.triggered.connect(window._open_catalog_editor)
        settings_menu.addAction(act_catalog_editor)
        
        settings_btn.setMenu(settings_menu)

        act_alerts = QAction("Enable Optional Alerts", window)
        act_alerts.setCheckable(True)
        act_alerts.setChecked(window._get_alerts_enabled())
        act_alerts.toggled.connect(window._set_alerts_enabled)
        settings_menu.addAction(act_alerts)

        # --- Bulk Menu ---
        bulk_btn = QToolButton()
        bulk_btn.setObjectName("BulkBtn")
        bulk_btn.setText("Bulk ▾")
        bulk_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        bulk_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        bulk_btn.setFixedHeight(36)
        
        bulk_menu = QMenu(bulk_btn)
        act_run_bulk = QAction("New Bulk Run", window)
        act_run_bulk.triggered.connect(window._start_bulk)
        act_bulk_settings = QAction("Bulk Settings", window)
        act_bulk_settings.triggered.connect(window._open_bulk_settings)
        bulk_menu.addAction(act_run_bulk)
        bulk_menu.addSeparator()
        bulk_menu.addAction(act_bulk_settings)
        bulk_btn.setMenu(bulk_menu)

        def _on_update():
            if not getattr(sys, "frozen", False):
                CustomMessageBox.info(window, "Failed", "You are not running a compiled version...", self._icon_dir)
            else:
                window._start_update_check(silent=False)

        bar = build_frameless_top_bar(
            window,
            WindowControlSpec(
                title=f"PmGen {CURRENT_VERSION}",
                icon_dir=self._icon_dir,
                on_minimize=window.showMinimized,
                on_toggle_fullscreen=window._toggle_fullscreen,
                on_close=window._confirm_exit,
                show_update=True,
                on_update=_on_update,
            ),
        )
        h_obj = bar.layout()
        nav = QWidget(bar)
        nav.setObjectName("TopBarNav")
        nav_l = QHBoxLayout(nav)
        nav_l.setContentsMargins(8, 0, 16, 0)
        nav_l.setSpacing(SPACING_SM)
        nav_l.addWidget(settings_btn)
        nav_l.addWidget(bulk_btn)
        if h_obj is not None:
            h_obj.insertWidget(0, nav, 0)  # type: ignore[attr-defined]

        tb.addWidget(bar)
        return tb

    def create_secondary_bar(self, window) -> QWidget:
        """
        Builds the bar containing User Info, Thresholds, and the ID Input field.
        """
        bar = QWidget(window)
        bar.setObjectName("SecondaryBar")
        bar.setFixedHeight(56)
        h = QHBoxLayout(bar)
        h.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)
        h.setSpacing(SPACING_SM)

        window.user_label = QLabel("Not signed in", bar)
        window.user_label.setObjectName("UserLabel")
        window.user_label.setProperty("class", "muted")
        h.addWidget(window.user_label, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch(1)

        window._thr_button = QPushButton("", bar)
        window._thr_button.setObjectName("ThresholdToggle")
        window._thr_button.setCursor(Qt.CursorShape.PointingHandCursor)
        window._thr_button.clicked.connect(window._toggle_threshold_enabled)
        window._thr_button.installEventFilter(window)

        window._basis_button = QPushButton("", bar)
        window._basis_button.setObjectName("BasisToggle")
        window._basis_button.setCursor(Qt.CursorShape.PointingHandCursor)
        window._basis_button.clicked.connect(window._toggle_life_basis)

        window._update_threshold_button()
        window._update_basis_button()

        h.addWidget(window._thr_button, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addWidget(window._basis_button, 0, Qt.AlignmentFlag.AlignVCenter)

        window._id_combo = QComboBox(bar)
        window._id_combo.setObjectName("IdInput")
        window._id_combo.setEditable(True)
        window._id_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        window._id_combo.setMaxVisibleItems(15) 
        window._id_combo.setMinimumWidth(200)
        window._id_combo.setFixedHeight(32)

        le = window._id_combo.lineEdit()
        le.setValidator(QRegularExpressionValidator(QRegularExpression(r"[A-Za-z0-9]*"), window))
        le.textChanged.connect(window._auto_capitalize)

        completer = QCompleter(window._id_combo.model(), window._id_combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        popup = completer.popup()
        if popup is not None:
            popup.setObjectName("IdCompleterPopup")
        window._id_combo.setCompleter(completer)

        window._load_id_history()

        window._generate_btn = QPushButton("Generate", bar)
        window._generate_btn.setObjectName("GenerateBtn")
        window._generate_btn.setProperty("class", "primary")
        window._generate_btn.setFixedHeight(32)
        window._generate_btn.clicked.connect(window._on_generate_clicked)

        h.addWidget(window._id_combo, 0)
        h.addWidget(window._generate_btn, 0)
        return bar
