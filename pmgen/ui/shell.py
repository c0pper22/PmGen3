"""Shared frameless window shell, top-bar controls, and resize behavior."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QEvent, QPoint, QRect, Qt
from PyQt6.QtGui import QAction, QCursor, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QMainWindow, QSizePolicy, QToolButton, QWidget

from .components import (
    CustomMessageBox,
    DialogTitleBar,
    DragRegion,
    FramelessDialog,
    LoadingDialog,
    ResizeState,
    TitleDragLabel,
)

BORDER_WIDTH = 8
TOP_BAR_HEIGHT = 64
SIDEBAR_WIDTH_EXPANDED = 240
SIDEBAR_WIDTH_COLLAPSED = 64


def resolve_icon_dir() -> str:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    return os.path.join(base_dir, "pmgen", "assets", "icons")


@dataclass
class WindowControlSpec:
    title: str
    icon_dir: str
    on_minimize: Callable[[], None]
    on_toggle_fullscreen: Callable[[bool], None]
    on_close: Callable[[], None]
    show_update: bool = False
    on_update: Callable[[], None] | None = None


def _icon_action(icon_dir: str, icon_name: str, text: str, parent: QWidget, callback) -> QAction:
    action = QAction(QIcon(os.path.join(icon_dir, icon_name)), text, parent)
    action.triggered.connect(callback)
    return action


def build_frameless_top_bar(window: QMainWindow, spec: WindowControlSpec) -> QWidget:
    bar = QWidget(window)
    bar.setObjectName("TopBarBg")
    bar.setFixedHeight(TOP_BAR_HEIGHT)
    bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    bar.setMouseTracking(True)

    layout = QHBoxLayout(bar)
    layout.setContentsMargins(BORDER_WIDTH, 0, BORDER_WIDTH, 0)
    layout.setSpacing(0)

    left_drag = DragRegion(window)
    title = TitleDragLabel(spec.title, window)
    right_drag = DragRegion(window)

    controls = QWidget(bar)
    control_layout = QHBoxLayout(controls)
    control_layout.setContentsMargins(0, 0, 0, 0)
    control_layout.setSpacing(0)

    if spec.show_update:
        btn_update = QToolButton(controls)
        btn_update.setObjectName("DialogBtn")
        icon_path = os.path.join(spec.icon_dir, "update.svg")
        if os.path.exists(icon_path):
            btn_update.setIcon(QIcon(icon_path))
        else:
            btn_update.setText("Update")
        btn_update.setToolTip("Check for Updates")
        if spec.on_update is not None:
            btn_update.clicked.connect(spec.on_update)
        control_layout.addWidget(btn_update)

    btn_min = QToolButton(controls)
    btn_min.setObjectName("DialogBtn")
    btn_min.setDefaultAction(_icon_action(spec.icon_dir, "minimize.svg", "Minimize", window, spec.on_minimize))

    window._act_full = QAction(QIcon(os.path.join(spec.icon_dir, "fullscreen.svg")), "Maximize", window)
    window._act_full.setCheckable(True)
    window._act_full.triggered.connect(spec.on_toggle_fullscreen)
    btn_full = QToolButton(controls)
    btn_full.setObjectName("DialogBtn")
    btn_full.setDefaultAction(window._act_full)

    btn_close = QToolButton(controls)
    btn_close.setObjectName("DialogBtn")
    btn_close.setDefaultAction(_icon_action(spec.icon_dir, "exit.svg", "Close", window, spec.on_close))

    control_layout.addWidget(btn_min)
    control_layout.addWidget(btn_full)
    control_layout.addWidget(btn_close)

    layout.addWidget(left_drag, 1)
    layout.addWidget(title, 0)
    layout.addWidget(right_drag, 1)
    layout.addWidget(controls, 0)
    return bar


class WindowResizeMixin:
    def _edge_flags_at_pos(self, pos_global: QPoint):
        pos = self.mapFromGlobal(pos_global)
        rect = self.rect()
        return (
            pos.x() <= BORDER_WIDTH,
            pos.x() >= rect.width() - BORDER_WIDTH,
            pos.y() <= BORDER_WIDTH,
            pos.y() >= rect.height() - BORDER_WIDTH,
        )

    def _update_cursor(self, pos_global: QPoint) -> None:
        if self.isFullScreen():
            self.unsetCursor()
            return
        left, right, top, bottom = self._edge_flags_at_pos(pos_global)
        if (left and top) or (right and bottom):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif (right and top) or (left and bottom):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif left or right:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif top or bottom:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def eventFilter(self, obj, event):
        if not self.isFullScreen() and event.type() in (
            QEvent.Type.MouseMove,
            QEvent.Type.HoverMove,
            QEvent.Type.Leave,
        ):
            self._update_cursor(QCursor.pos())
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.isFullScreen():
            left, right, top, bottom = self._edge_flags_at_pos(event.globalPosition().toPoint())
            if any((left, right, top, bottom)):
                self._rs = ResizeState(
                    True,
                    left,
                    right,
                    top,
                    bottom,
                    event.globalPosition().toPoint(),
                    self.geometry(),
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._rs.resizing and not self.isFullScreen():
            delta = event.globalPosition().toPoint() - self._rs.press_pos
            geom = QRect(self._rs.press_geom)
            if self._rs.edge_left:
                geom.setLeft(min(geom.left() + delta.x(), geom.right() - 200))
            elif self._rs.edge_right:
                geom.setRight(max(self._rs.press_geom.right() + delta.x(), geom.left() + 200))
            if self._rs.edge_top:
                geom.setTop(min(geom.top() + delta.y(), geom.bottom() - 150))
            elif self._rs.edge_bottom:
                geom.setBottom(max(self._rs.press_geom.bottom() + delta.y(), geom.top() + 150))
            self.setGeometry(geom)
            event.accept()
            return

        if not self.isFullScreen():
            self._update_cursor(event.globalPosition().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._rs.resizing:
            self._rs = ResizeState()
            self._update_cursor(QCursor.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        if not self.isFullScreen():
            self._update_cursor(QCursor.pos())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)
