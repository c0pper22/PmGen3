"""Donut/ring chart widget for the wear overview summary."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class DonutChart(QWidget):
    """A donut/ring chart showing due vs. OK counts with center text."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._due_count: int = 0
        self._ok_count: int = 0
        self._total_items: int = 0
        self._highest_pct: float = 0.0

        # Colors — overridable for theme support
        self._due_color = QColor("#e74c3c")
        self._ok_color = QColor("#2ecc71")
        self._bg_ring_color = QColor("#3a3f4b")
        self._text_color = QColor("#e0e0e0")
        self._sub_text_color = QColor("#909090")

        self.setMinimumSize(140, 140)

    # ---- public API ----

    def set_data(self, due_count: int, ok_count: int, total_items: int, highest_pct: float) -> None:
        self._due_count = due_count
        self._ok_count = ok_count
        self._total_items = total_items
        self._highest_pct = highest_pct
        self.update()

    def set_colors(
        self,
        due: QColor,
        ok: QColor,
        bg_ring: QColor,
        text: QColor,
        sub_text: QColor,
    ) -> None:
        self._due_color = due
        self._ok_color = ok
        self._bg_ring_color = bg_ring
        self._text_color = text
        self._sub_text_color = sub_text
        self.update()

    # ---- paint ----

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        side = min(w, h)
        ring_width = max(8, side * 0.12)
        margin = ring_width / 2.0 + 2

        cx = w / 2.0
        cy = h / 2.0
        radius = (side / 2.0) - margin

        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        total = self._due_count + self._ok_count

        if total <= 0:
            # Empty state: full gray ring
            pen = QPen(self._bg_ring_color, ring_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, 0, 360 * 16)
        else:
            due_angle = int(360 * self._due_count / total * 16)
            ok_angle = 360 * 16 - due_angle

            # OK arc (drawn first, underneath)
            pen = QPen(self._ok_color, ring_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, 90 * 16, ok_angle)

            # Due arc (drawn on top)
            if due_angle > 0:
                pen = QPen(self._due_color, ring_width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawArc(rect, (90 * 16) - ok_angle, due_angle)

        # Center text
        due_font = QFont()
        due_font.setPixelSize(max(14, int(side * 0.18)))
        due_font.setBold(True)
        painter.setFont(due_font)
        painter.setPen(self._text_color)

        due_text = str(self._due_count)
        painter.drawText(QRectF(0, cy - radius * 0.35, w, radius * 0.5), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, due_text)

        due_label_font = QFont()
        due_label_font.setPixelSize(max(10, int(side * 0.09)))
        painter.setFont(due_label_font)
        painter.setPen(self._due_color)
        painter.drawText(QRectF(0, cy - radius * 0.10, w, radius * 0.25), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, "due")

        sub_font = QFont()
        sub_font.setPixelSize(max(9, int(side * 0.08)))
        painter.setFont(sub_font)
        painter.setPen(self._sub_text_color)
        painter.drawText(QRectF(0, cy + radius * 0.12, w, radius * 0.4), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{self._total_items} total items")

        painter.end()

    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(140, 140)
