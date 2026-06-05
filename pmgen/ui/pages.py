"""Page widgets that compose the main dashboard tabs without owning app logic."""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtWidgets import QPlainTextEdit, QTabBar, QTabWidget, QVBoxLayout, QWidget

from .factory import UIFactory
from .inventory import InventoryTab
from .theme import SPACING_MD


class MainWindowProtocol(Protocol):
    editor: QPlainTextEdit


class SingleReportPage(QWidget):
    def __init__(self, window: MainWindowProtocol, icon_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabHome")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        factory = UIFactory(icon_dir)
        window._secondary_bar = factory.create_secondary_bar(window)
        layout.addWidget(window._secondary_bar, 0)

        window.editor = QPlainTextEdit()
        window.editor.setObjectName("MainEditor")
        window.editor.setReadOnly(True)
        window.editor.setMaximumBlockCount(2000)
        window.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(window.editor, 1)


class InventoryPage(QWidget):
    def __init__(self, window, icon_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabInventoryPage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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

    def add_pinned_tab(self, widget: QWidget, title: str) -> int:
        index = self.addTab(widget, title)
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        return index
