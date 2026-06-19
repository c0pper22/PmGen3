"""Page widgets that compose the main dashboard tabs without owning app logic."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import (
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .factory import UIFactory
from .icons import set_themed_icon
from .inventory import InventoryTab
from .theme import SPACING_MD, SPACING_SM
from .widget_report import WidgetReportView

REPORT_STYLE_KEY = "ui/single_report_style"


class MainWindowProtocol(Protocol):
    editor: QPlainTextEdit


class SingleReportPage(QWidget):
    def __init__(self, window: MainWindowProtocol, icon_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabHome")
        self._window = window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_SM, 0, 0)
        layout.setSpacing(SPACING_MD)

        factory = UIFactory(icon_dir)
        window._secondary_bar = factory.create_secondary_bar(window)  # type: ignore[attr-defined]
        layout.addWidget(window._secondary_bar, 0)  # type: ignore[attr-defined]

        # Stacked widget to switch between text and rich widget views
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        # Index 0: plain text editor (legacy)
        self._editor = QPlainTextEdit()
        self._editor.setObjectName("MainEditor")
        self._editor.setReadOnly(True)
        self._editor.setMaximumBlockCount(2000)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._stack.addWidget(self._editor)

        # Index 1: rich widget view
        self._widget_view = WidgetReportView()
        self._stack.addWidget(self._widget_view)

        # Always expose the editor on the window for backward compat
        window.editor = self._editor
        window._widget_view = self._widget_view  # type: ignore[attr-defined]

        # Apply initial view mode from settings
        mode = QSettings().value(REPORT_STYLE_KEY, "widget", str)
        self.set_view_mode(mode)

    def set_view_mode(self, mode: str) -> None:
        """Switch between 'widget' and 'text' display modes."""
        if mode == "text":
            self._stack.setCurrentIndex(0)
        else:
            self._stack.setCurrentIndex(1)

        QSettings().setValue(REPORT_STYLE_KEY, mode)

    def view_mode(self) -> str:
        return QSettings().value(REPORT_STYLE_KEY, "widget", str)


class InventoryPage(QWidget):
    def __init__(self, window, icon_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabInventoryPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_SM, 0, 0)
        layout.setSpacing(0)
        window.tab_tools = InventoryTab(window, icon_dir=icon_dir)
        window.tab_tools.setObjectName("TabInventory")
        layout.addWidget(window.tab_tools)


class DashboardTabs(QTabWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("MainTabs")
        self.setDocumentMode(True)
        self.setTabsClosable(True)

    def tabInserted(self, index: int) -> None:
        super().tabInserted(index)
        btn = QPushButton(self)
        btn.setFixedSize(18, 18)
        btn.setFlat(True)
        btn.setProperty("class", "tab-close")
        btn.clicked.connect(lambda _checked=False, i=index: self.tabCloseRequested.emit(i))
        set_themed_icon(btn, "exit", _icon_dir())
        tab_bar = self.tabBar()
        if tab_bar is not None:
            tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def add_pinned_tab(self, widget: QWidget, title: str) -> int:
        index = self.addTab(widget, title)
        tab_bar = self.tabBar()
        if tab_bar is not None:
            tab_bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        return index


def _icon_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "assets" / "icons")
