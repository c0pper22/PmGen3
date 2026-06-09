"""Page widgets that compose the main dashboard tabs without owning app logic."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PyQt6.QtWidgets import QPlainTextEdit, QPushButton, QTabBar, QTabWidget, QVBoxLayout, QWidget

from .factory import UIFactory
from .icons import set_themed_icon
from .inventory import InventoryTab
from .theme import SPACING_MD, SPACING_SM


class MainWindowProtocol(Protocol):
    editor: QPlainTextEdit


class SingleReportPage(QWidget):
    def __init__(self, window: MainWindowProtocol, icon_dir: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("TabHome")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_SM, 0, 0)
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
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, btn)

    def add_pinned_tab(self, widget: QWidget, title: str) -> int:
        index = self.addTab(widget, title)
        self.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        return index


def _icon_dir() -> str:
    return str(Path(__file__).resolve().parents[1] / "assets" / "icons")
