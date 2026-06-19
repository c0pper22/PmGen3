"""Donut/ring chart widget for the wear overview summary."""

from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPaintEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class DonutChart(QWidget):
    """A donut/ring chart showing due vs. OK counts with center text."""

    MIN_SIZE = 140
    START_ANGLE = 90 * 16  # Qt angles are 1/16 degree; 90 degrees is 12 o'clock.
    FULL_CIRCLE = 360 * 16

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._due_count: int = 0
        self._ok_count: int = 0
        self._total_items: int = 0
        self._highest_pct: float = 0.0

        # Colors — overridable for theme support.
        self._due_color = QColor("#e74c3c")
        self._ok_color = QColor("#2ecc71")
        self._bg_ring_color = QColor("#3a3f4b")
        self._text_color = QColor("#e0e0e0")
        self._sub_text_color = QColor("#909090")

        self.setMinimumSize(self.MIN_SIZE, self.MIN_SIZE)

    # ---- public API ----

    def set_data(self, due_count: int, ok_count: int, total_items: int, highest_pct: float) -> None:
        """Update chart values and trigger a repaint."""
        self._due_count = max(0, int(due_count))
        self._ok_count = max(0, int(ok_count))
        self._total_items = max(0, int(total_items))
        self._highest_pct = max(0.0, float(highest_pct))
        self.update()

    def set_colors(
        self,
        due: QColor,
        ok: QColor,
        bg_ring: QColor,
        text: QColor,
        sub_text: QColor,
    ) -> None:
        """Update chart colors and trigger a repaint."""
        self._due_color = QColor(due)
        self._ok_color = QColor(ok)
        self._bg_ring_color = QColor(bg_ring)
        self._text_color = QColor(text)
        self._sub_text_color = QColor(sub_text)
        self.update()

    # ---- paint helpers ----

    @staticmethod
    def _ring_pen(color: QColor, width: float) -> QPen:
        pen = QPen(color)
        pen.setWidthF(width)
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        return pen

    def _draw_full_ring(self, painter: QPainter, rect: QRectF, width: float, color: QColor) -> None:
        painter.setPen(self._ring_pen(color, width))
        painter.drawEllipse(rect)

    def _draw_arc(
        self,
        painter: QPainter,
        rect: QRectF,
        width: float,
        color: QColor,
        start_angle: int,
        span_angle: int,
    ) -> None:
        if span_angle == 0:
            return

        painter.setPen(self._ring_pen(color, width))
        painter.drawArc(rect, start_angle, span_angle)

    # ---- paint ----

    def paintEvent(self, event: QPaintEvent | None) -> None:
        _ = event

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        width = self.width()
        height = self.height()
        side = min(width, height)

        ring_width = max(10.0, side * 0.12)
        margin = (ring_width / 2.0) + 2.0
        radius = max(1.0, (side / 2.0) - margin)

        center_x = width / 2.0
        center_y = height / 2.0
        ring_rect = QRectF(
            center_x - radius,
            center_y - radius,
            radius * 2.0,
            radius * 2.0,
        )

        due_count = self._due_count
        ok_count = self._ok_count
        chart_total = due_count + ok_count

        # Always draw the neutral ring first. This gives empty states a visible ring and
        # prevents small anti-aliased seams from showing the widget background.
        self._draw_full_ring(painter, ring_rect, ring_width, self._bg_ring_color)

        if chart_total > 0:
            if due_count == chart_total:
                self._draw_full_ring(painter, ring_rect, ring_width, self._due_color)
            elif ok_count == chart_total:
                self._draw_full_ring(painter, ring_rect, ring_width, self._ok_color)
            else:
                # Qt draws positive spans counter-clockwise. Negative spans draw clockwise,
                # which is usually what users expect from a 12 o'clock starting position.
                due_angle = round(self.FULL_CIRCLE * (due_count / chart_total))
                due_angle = min(max(1, due_angle), self.FULL_CIRCLE - 1)
                ok_angle = self.FULL_CIRCLE - due_angle

                due_span = -due_angle
                ok_span = -ok_angle

                # Put the important value first: red starts at 12 o'clock, green follows it.
                self._draw_arc(
                    painter,
                    ring_rect,
                    ring_width,
                    self._due_color,
                    self.START_ANGLE,
                    due_span,
                )
                self._draw_arc(
                    painter,
                    ring_rect,
                    ring_width,
                    self._ok_color,
                    self.START_ANGLE + due_span,
                    ok_span,
                )

        # Center text.
        due_font = QFont(self.font())
        due_font.setPixelSize(max(16, int(side * 0.20)))
        due_font.setBold(True)

        sub_font = QFont(self.font())
        sub_font.setPixelSize(max(9, int(side * 0.08)))

        due_metrics = QFontMetrics(due_font)
        sub_metrics = QFontMetrics(sub_font)
        spacing = max(2, int(side * 0.02))
        text_block_height = due_metrics.height() + spacing + sub_metrics.height()
        text_top = center_y - (text_block_height / 2.0)

        painter.setPen(self._text_color)
        painter.setFont(due_font)
        painter.drawText(
            QRectF(0, text_top, width, due_metrics.height()),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            str(due_count),
        )

        display_total = self._total_items if self._total_items > 0 else chart_total
        painter.setPen(self._sub_text_color)
        painter.setFont(sub_font)
        painter.drawText(
            QRectF(0, text_top + due_metrics.height() + spacing, width, sub_metrics.height()),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            f"{display_total} total items",
        )

        painter.end()

    def sizeHint(self) -> QSize:
        return self.minimumSizeHint()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.MIN_SIZE, self.MIN_SIZE)
