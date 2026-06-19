from dataclasses import dataclass
from PyQt6.QtCore import Qt, QPoint, QRect, QSize
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QWidget, QMainWindow, QLabel, QDialog, QHBoxLayout, 
    QToolButton, QVBoxLayout, QFrame, QPushButton, QSizePolicy, QProgressBar
)

from .icons import set_themed_icon

# ---------------------------- Drag Helpers ----------------------------
class DragRegion(QWidget):
    def __init__(self, parent_window: QMainWindow):
        super().__init__(parent_window)
        self._win = parent_window
        self._dragging = False
        self._drag_pos = QPoint()
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            e.accept()
        else:
            super().mouseReleaseEvent(e)

class TitleDragLabel(QLabel):
    def __init__(self, text: str, parent_window: QMainWindow):
        super().__init__(text, parent_window)
        self._win = parent_window
        self._dragging = False
        self._drag_pos = QPoint()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(36)
        self.setObjectName("TitleLabel")
        self.setMouseTracking(True)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._dragging and not self._win.isFullScreen():
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            e.accept()
        else:
            super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            if self._win.isFullScreen():
                if hasattr(self._win, "_act_full"):
                    self._win._act_full.setChecked(False)
                self._win.showNormal()
            else:
                if hasattr(self._win, "_act_full"):
                    self._win._act_full.setChecked(True)
                self._win.showFullScreen()
            e.accept()
        else:
            super().mouseDoubleClickEvent(e)

# ---------------------------- Custom TitleBar for dialogs ----------------------------
class DialogTitleBar(QWidget):
    def __init__(self, window: QDialog, title: str, icon_dir: str):
        super().__init__(window)
        self.setObjectName("DialogTitleBar")
        self._win = window
        self._dragging = False
        self._drag_pos = QPoint()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        lbl = QLabel(title, self)
        lbl.setObjectName("DialogTitleLabel")

        btn_min = QToolButton(self)
        btn_min.setObjectName("DialogBtn")
        btn_min.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn_min.setIconSize(QSize(14, 14))
        set_themed_icon(btn_min, "minimize", icon_dir)
        btn_min.setToolTip("Minimize")
        btn_min.clicked.connect(self._win.showMinimized)

        self._act_max = QAction("Maximize", self)
        set_themed_icon(self._act_max, "fullscreen", icon_dir)
        self._act_max.setCheckable(True)
        self._act_max.triggered.connect(self._toggle_max_restore)
        btn_max = QToolButton(self)
        btn_max.setObjectName("DialogBtn")
        btn_max.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn_max.setIconSize(QSize(14, 14))
        btn_max.setDefaultAction(self._act_max)

        btn_close = QToolButton(self)
        btn_close.setObjectName("DialogBtn")
        btn_close.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn_close.setIconSize(QSize(14, 14))
        set_themed_icon(btn_close, "exit", icon_dir)
        btn_close.setToolTip("Close")
        btn_close.clicked.connect(self._win.close)

        layout.addWidget(lbl, 1, Qt.AlignmentFlag.AlignVCenter)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        box = QWidget(self)
        box.setObjectName("DialogBtnGroup")
        box.setLayout(right)
        right.addWidget(btn_min)
        right.addWidget(btn_max)
        right.addWidget(btn_close)
        layout.addWidget(box, 0)
        self.setFixedHeight(36)

    def _toggle_max_restore(self, checked: bool):
        if checked:
            self._win.showMaximized()
        else:
            self._win.showNormal()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)
    def mouseMoveEvent(self, e):
        if self._dragging:
            self._win.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()
        else:
            super().mouseMoveEvent(e)
    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            e.accept()
        else:
            super().mouseReleaseEvent(e)

# ---------------------------- FramelessDialog base ----------------------------
class FramelessDialog(QDialog):
    def __init__(self, parent, title: str, icon_dir: str):
        super().__init__(parent, flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setObjectName("FramelessDialogRoot")
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)

        self._frame = QWidget(self)
        self._frame.setObjectName("FramelessDialogFrame")
        outer.addWidget(self._frame)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self._titlebar = DialogTitleBar(self, title, icon_dir)
        frame_layout.addWidget(self._titlebar)

        sep = QFrame(self._frame)
        sep.setObjectName("DialogSeparator")
        sep.setFrameShape(QFrame.Shape.NoFrame)
        frame_layout.addWidget(sep)

        self._content = QWidget(self._frame)
        self._content.setObjectName("DialogContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(12)
        frame_layout.addWidget(self._content)
        self.setMinimumSize(420, 220)

# ---------------------------- CustomMessageBox ----------------------------
class CustomMessageBox(FramelessDialog):
    def __init__(self, parent, title: str, text: str, icon_dir: str, buttons: list[tuple[str, str]]):
        super().__init__(parent, title, icon_dir)
        lbl = QLabel(text, self._content)
        lbl.setWordWrap(True)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._clicked_role: str | None = None
        for label, role in buttons:
            b = QPushButton(label, self._content)
            b.clicked.connect(lambda _=False, r=role: self._finish(r))
            btn_row.addWidget(b)
        self._content_layout.addWidget(lbl)
        self._content_layout.addLayout(btn_row)

    def _finish(self, role: str):
        self._clicked_role = role
        self.accept()

    @staticmethod
    def none(parent, title: str, text: str, icon_dir: str):
        dlg = CustomMessageBox(parent, title, text, icon_dir, [])
        dlg.exec()
        return dlg._clicked_role or "ok"

    @staticmethod
    def info(parent, title: str, text: str, icon_dir: str):
        dlg = CustomMessageBox(parent, title, text, icon_dir, [("OK", "ok")])
        dlg.exec()
        return dlg._clicked_role or "ok"

    @staticmethod
    def warn(parent, title: str, text: str, icon_dir: str):
        dlg = CustomMessageBox(parent, title, text, icon_dir, [("OK", "ok")])
        dlg.exec()
        return dlg._clicked_role or "ok"

    @staticmethod
    def apply(parent, title: str, text: str, icon_dir: str):
        dlg = CustomMessageBox(parent, title, text, icon_dir, [("CANCEL", "cancel"),("APPLY", "apply")])
        dlg.exec()
        return dlg._clicked_role or "ok"

    @staticmethod
    def confirm(parent, title: str, text: str, icon_dir: str):
        dlg = CustomMessageBox(parent, title, text, icon_dir, [("Cancel", "cancel"), ("OK", "ok")])
        dlg.exec()
        return dlg._clicked_role or "cancel"

@dataclass
class ResizeState:
    resizing: bool = False
    edge_left: bool = False
    edge_right: bool = False
    edge_top: bool = False
    edge_bottom: bool = False
    press_pos: QPoint = QPoint()
    press_geom: QRect = QRect()

# ---------------------------- Loading Dialog ----------------------------
class LoadingDialog(FramelessDialog):
    def __init__(self, parent, title: str, message: str, icon_dir: str):
        super().__init__(parent, title, icon_dir)
        
        if hasattr(self._titlebar, "_act_max"):
            for child in self._titlebar.findChildren(QToolButton):
                child.hide()

        self.message_label = QLabel(message, self._content)
        self.message_label.setObjectName("DialogLabel")
        
        self.progress_bar = QProgressBar(self._content)
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(12)
        
        self._content_layout.addWidget(self.message_label)
        self._content_layout.addWidget(self.progress_bar)
        self._content_layout.addStretch(1)
        
        self.setMinimumSize(350, 130)
        self.resize(350, 130)
