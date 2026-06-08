"""Shared frameless window shell, top-bar controls, and resize behavior."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QEvent, QPoint, QRect, QSettings, Qt
from PyQt6.QtGui import QAction, QCursor, QPainterPath, QRegion
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
from .icons import set_themed_icon

BORDER_WIDTH = 8
TOP_BAR_HEIGHT = 56
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
    action = QAction(text, parent)
    set_themed_icon(action, icon_name.removesuffix(".svg"), icon_dir)
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
    left_drag.setObjectName("TopBarDragRegion")
    title = TitleDragLabel(spec.title, window)
    right_drag = DragRegion(window)
    right_drag.setObjectName("TopBarDragRegion")

    controls = QWidget(bar)
    controls.setObjectName("TopBarControls")
    control_layout = QHBoxLayout(controls)
    control_layout.setContentsMargins(0, 0, 0, 0)
    control_layout.setSpacing(0)

    if spec.show_update:
        btn_update = QToolButton(controls)
        btn_update.setObjectName("DialogBtn")
        btn_update.setFixedSize(36, 36)
        set_themed_icon(btn_update, "update", spec.icon_dir)
        btn_update.setToolTip("Check for Updates")
        if spec.on_update is not None:
            btn_update.clicked.connect(spec.on_update)
        control_layout.addWidget(btn_update)

    btn_min = QToolButton(controls)
    btn_min.setObjectName("DialogBtn")
    btn_min.setFixedSize(36, 36)
    btn_min.setDefaultAction(_icon_action(spec.icon_dir, "minimize.svg", "Minimize", window, spec.on_minimize))

    window._act_full = QAction("Maximize", window)
    set_themed_icon(window._act_full, "fullscreen", spec.icon_dir)
    window._act_full.setCheckable(True)
    window._act_full.triggered.connect(spec.on_toggle_fullscreen)
    btn_full = QToolButton(controls)
    btn_full.setObjectName("DialogBtn")
    btn_full.setFixedSize(36, 36)
    btn_full.setDefaultAction(window._act_full)

    btn_close = QToolButton(controls)
    btn_close.setObjectName("DialogBtn")
    btn_close.setFixedSize(36, 36)
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

    # ------------------------------------------------------------------
    #  Rounded window corners via QRegion mask
    # ------------------------------------------------------------------

    def _read_corner_strength(self) -> int:
        """Read the corner roundness preference (0-100) from QSettings."""
        try:
            v = int(QSettings().value("ui/corner_roundness", 50, int))
        except (TypeError, ValueError):
            v = 50
        return max(0, min(100, v))

    @staticmethod
    def _corner_radius_px(strength: int) -> int:
        """Map corner strength 0-100 to a pixel corner radius."""
        if strength <= 0:
            return 0
        return max(1, int(round(20.0 * strength / 100.0)))

    def apply_window_roundness(self, strength: int | None = None) -> None:
        """Apply a rounded-rect mask to this frameless window."""
        if strength is None:
            strength = self._read_corner_strength()
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            return
        radius = self._corner_radius_px(strength)
        if radius <= 0:
            self.clearMask()
            return
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event):
        """Re-apply the rounded mask on resize (debounced to 60 fps)."""
        super().resizeEvent(event)
        if not hasattr(self, "_mask_timer"):
            from PyQt6.QtCore import QTimer
            self._mask_timer = QTimer(self)
            self._mask_timer.setSingleShot(True)
            self._mask_timer.setInterval(16)
            self._mask_timer.timeout.connect(self.apply_window_roundness)
        self._mask_timer.start()

    def changeEvent(self, event):
        """Clear or re-apply the mask when window state changes."""
        if event.type() == QEvent.Type.WindowStateChange:
            self.apply_window_roundness()
        super().changeEvent(event)
