"""Rich widget-based single report view replacing the plain-text editor."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pmgen.types import SingleReportData
from .donut_chart import DonutChart
from .theme import (
    CORNER_ROUNDNESS_KEY,
    RADIUS_MD,
    RADIUS_LG,
    _corner_scale,
    _scaled_radius,
)

# ── helpers ──────────────────────────────────────────────────────────────────

def _is_dark_mode() -> bool:
    mode = QSettings().value("ui/theme_mode", "dark", str)
    return mode != "light"


def _theme_colors():
    """Return a dict of theme-aware colors for widget styling."""
    if _is_dark_mode():
        return {
            "bg": QColor("#171A20"),
            "surface": QColor("#20242C"),
            "surface_high": QColor("#2A2F38"),
            "border": QColor("#303642"),
            "text": QColor("#F1F3F5"),
            "muted": QColor("#A7ADB7"),
            "primary": QColor("#0066ff"),
            "primary_text": QColor("#ffffff"),
            "danger": QColor("#e74c3c"),
            "danger_bg": QColor("#3d1f1f"),
            "success": QColor("#2ecc71"),
            "success_bg": QColor("#1a3a2a"),
            "warning": QColor("#f39c12"),
            "warning_bg": QColor("#3d2e0a"),
            "accent": QColor("#b2c5ff"),
        }
    return {
        "bg": QColor("#faf9ff"),
        "surface": QColor("#ffffff"),
        "surface_high": QColor("#f1f3ff"),
        "border": QColor("#c3c6d6"),
        "text": QColor("#051a3e"),
        "muted": QColor("#737685"),
        "primary": QColor("#003d9b"),
        "primary_text": QColor("#ffffff"),
        "danger": QColor("#ba1a1a"),
        "danger_bg": QColor("#ffdad6"),
        "success": QColor("#1e7d4a"),
        "success_bg": QColor("#d1fae5"),
        "warning": QColor("#b45309"),
        "warning_bg": QColor("#fef3c7"),
        "accent": QColor("#003d9b"),
    }


def _section_label(text: str, colors: dict) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"QLabel {{"
        f"  color: {colors['accent'].name()};"
        f"  font-weight: 700;"
        f"  font-size: 15px;"
        f"  padding: 0;"
        f"  margin: 0;"
        f"}}"
    )
    return lbl


def _section_header(text: str, colors: dict, on_copy: callable) -> QWidget:
    """Section label + material copy icon button."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)

    label = _section_label(text, colors)
    row.addWidget(label)

    btn = QToolButton()
    btn.setText("\u29c9")  # ⧉ copy icon
    btn.setToolTip("Copy table to clipboard")
    btn.setFixedSize(24, 24)
    r_md = _corner_radii()["md"]
    btn.setStyleSheet(
        f"QToolButton {{"
        f"  background-color: transparent;"
        f"  color: {colors['muted'].name()};"
        f"  border: 1px solid {colors['border'].name()};"
        f"  border-radius: {r_md}px;"
        f"  font-size: 14px;"
        f"  padding: 0;"
        f"}}"
        f"QToolButton:hover {{"
        f"  background-color: {colors['surface_high'].name()};"
        f"  color: {colors['accent'].name()};"
        f"}}"
    )
    btn.clicked.connect(on_copy)
    row.addWidget(btn)
    row.addStretch()
    return w


def _copy_tsv(headers: list[str], rows: list[list[str]]) -> None:
    """Copy table data to the system clipboard with columns separated by ' — '."""
    sep = " — "
    lines = [sep.join(headers)]
    for row in rows:
        lines.append(sep.join(row))
    QApplication.clipboard().setText("\n".join(lines))


def _separator(colors: dict) -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"QFrame {{ color: {colors['border'].name()}; }}")
    line.setFixedHeight(1)
    return line


def _corner_radii() -> dict[str, int]:
    """Return radius tokens scaled by the user's corner roundness slider (0–100)."""
    strength = int(QSettings().value(CORNER_ROUNDNESS_KEY, 50, int))
    scale = _corner_scale(strength)
    return {
        "md": _scaled_radius(RADIUS_MD, scale),
        "lg": _scaled_radius(RADIUS_LG, scale),
        "badge": min(_scaled_radius(RADIUS_LG, scale), 10),  # cap for pill-shaped badges
    }


def _pill_label(text: str, bg: str, fg: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setFixedHeight(25)
    lbl.setFixedWidth(50)
    lbl.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    r = _corner_radii()["badge"]
    lbl.setStyleSheet(
        f"QLabel {{"
        f"  background-color: {bg};"
        f"  color: {fg};"
        f"  border-radius: {r}px;"
        f"  padding: 1px 6px;"
        f"  font-weight: 600;"
        f"  font-size: 10px;"
        f"}}"
    )
    return lbl


# ── WearBar ──────────────────────────────────────────────────────────────────

class _WearBar(QWidget):
    """Horizontal bar showing wear percentage with color-coding."""

    def __init__(self, pct: float, is_due: bool, colors: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self._pct = min(pct, 150.0)  # cap at 150% for display
        self._is_due = is_due
        self._colors = colors
        self.setFixedHeight(16)
        self.setMinimumWidth(80)

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # Scale corner radius by user's corner roundness slider, capped at pill shape
        scale = _corner_scale(int(QSettings().value(CORNER_ROUNDNESS_KEY, 50, int)))
        radius = min(int(h / 2 * scale), h / 2)

        # Background track
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._colors['border'])
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        if self._pct <= 0:
            painter.end()
            return

        fill_w = int(w * min(self._pct, 100.0) / 100.0)
        fill_w = max(fill_w, 4)  # minimum visible sliver

        # Color: green → yellow → red based on pct
        bar_color = _wear_color(self._pct)

        painter.setBrush(bar_color)
        painter.drawRoundedRect(0, 0, fill_w, h, radius, radius)

        painter.end()

    def sizeHint(self):
        from PyQt6.QtCore import QSize
        return QSize(100, 16)


def _wear_color(pct: float) -> QColor:
    """Interpolate green → yellow → red based on wear percentage."""
    pct = max(0.0, min(pct, 100.0))
    if pct <= 50.0:
        t = pct / 50.0
        r = int(0x2e + t * (0xf3 - 0x2e))
        g = int(0xcc + t * (0x9c - 0xcc))
        b = int(0x71 + t * (0x12 - 0x71))
    else:
        t = (pct - 50.0) / 50.0
        r = int(0xf3 + t * (0xe7 - 0xf3))
        g = int(0x9c + t * (0x4c - 0x9c))
        b = int(0x12 + t * (0x3c - 0x12))
    return QColor(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


class _CenterWidget(QWidget):
    """Container that vertically centers a child widget without squeezing it."""

    def __init__(self, child: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self._child = child
        child.setParent(self)
        self.setStyleSheet("background: transparent;")

    def sizeHint(self):
        return self._child.sizeHint()

    def minimumSizeHint(self):
        return self._child.minimumSizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        ch = self._child.sizeHint().height()
        self._child.setGeometry(0, (self.height() - ch) // 2, self.width(), ch)


# ── WidgetReportView ─────────────────────────────────────────────────────────

class WidgetReportView(QWidget):
    """Rich widget-based single report display."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._data: SingleReportData | None = None

        # Scroll area wrapping the whole content
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._content = QWidget()
        self._scroll.setWidget(self._content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll)

        # Build the initial empty/placeholder layout
        self._build_layout()

    # ── public ───────────────────────────────────────────────────────────────

    def set_report_data(self, data: SingleReportData) -> None:
        self._data = data
        self._rebuild()

    def clear(self) -> None:
        self._data = None
        self._rebuild()

    def refresh_theme(self) -> None:
        if self._data is not None:
            self._rebuild()

    # ── internal build ───────────────────────────────────────────────────────

    def _build_layout(self) -> None:
        """Create the placeholder/empty layout for the content widget."""
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(12)

        placeholder = QLabel("Enter a serial number and click Generate to see the report.")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder.setStyleSheet("color: #888; font-size: 14px; padding: 40px;")
        placeholder.setObjectName("_placeholder")
        layout.addWidget(placeholder, 1)
        layout.addStretch()

    def _clear_content(self) -> None:
        """Remove all children from the content widget, recursively."""
        old = self._content.layout()
        if old is not None:
            self._clear_layout(old)

    @staticmethod
    def _clear_layout(layout) -> None:
        """Recursively remove and delete all widgets from a layout."""
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            else:
                sub = child.layout()
                if sub is not None:
                    WidgetReportView._clear_layout(sub)

    def _rebuild(self) -> None:
        self._clear_content()
        if self._data is None:
            self._build_layout()
            return

        data = self._data
        colors = _theme_colors()
        r = _corner_radii()
        self._content.setStyleSheet(
            f"background-color: {colors['bg'].name()};"
            f" border-radius: {r['lg']}px;"
        )

        layout = self._content.layout()
        if layout is None:
            layout = QVBoxLayout(self._content)
            layout.setContentsMargins(16, 8, 16, 16)
            layout.setSpacing(12)

        # ── 1. Full-width info bar (no background card) ──
        self._build_info_bar(layout, data, colors)

        # ── 2. Full-width alerts ──
        self._build_alerts(layout, data, colors)

        # ── 3. Counters + Error History + Summary side by side ──

        # Counters (left, compact)
        counters_col = QVBoxLayout()
        counters_col.setSpacing(8)
        self._build_counters(counters_col, data, colors)
        counters_wrap = QWidget()
        counters_wrap.setLayout(counters_col)

        # Error History (middle, scrollable)
        err_col = QVBoxLayout()
        err_col.setSpacing(8)
        self._build_error_history(err_col, data, colors)
        err_wrap = QWidget()
        err_wrap.setLayout(err_col)

        # Summary (right, inline, no card background)
        summary_col = QVBoxLayout()
        summary_col.setSpacing(8)
        self._build_summary_inline(summary_col, data, colors)
        summary_wrap = QWidget()
        summary_wrap.setLayout(summary_col)
        summary_wrap.setFixedWidth(260)

        # Inline labels row: Counters | Error History | Summary
        labels_row = QHBoxLayout()
        labels_row.setSpacing(16)
        labels_row.addWidget(_section_label("Counters", colors))
        labels_row.addSpacing(285)

        def _copy_error_history() -> None:
            headers = ["Code", "Counter", "Date", "Time"]
            rows: list[list[str]] = []
            for rec in data.error_records:
                rows.append([rec.code, rec.counter, rec.date, rec.time])
            _copy_tsv(headers, rows)

        labels_row.addWidget(_section_header("Error History", colors, _copy_error_history))
        labels_row.addStretch()
        summary_label_wrap = QWidget()
        summary_label_wrap.setFixedWidth(260)
        sl_layout = QHBoxLayout(summary_label_wrap)
        sl_layout.setContentsMargins(0, 0, 0, 0)
        sl_layout.addWidget(_section_label("Summary", colors))
        sl_layout.addStretch()
        labels_row.addWidget(summary_label_wrap)
        layout.addLayout(labels_row)

        # Content row
        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        content_row.addWidget(counters_wrap, 0)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setStyleSheet(f"QFrame {{ color: {colors['border'].name()}; }}")
        sep2.setFixedWidth(1)
        content_row.addWidget(sep2, 0)
        content_row.addWidget(err_wrap, 1)
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setStyleSheet(f"QFrame {{ color: {colors['border'].name()}; }}")
        sep3.setFixedWidth(1)
        content_row.addWidget(sep3, 0)
        content_row.addWidget(summary_wrap, 0)
        layout.addLayout(content_row)

        # ── 5. Wear Analysis table ──
        self._build_wear_table(layout, data, colors)

        # ── 6. Final Parts ──
        self._build_final_parts(layout, data, colors)

        layout.addStretch()

    # ── sections ─────────────────────────────────────────────────────────────

    def _build_info_bar(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        """Full-width info bar — plain text, no background card, no threshold/basis."""
        container = QWidget()
        container.setObjectName("InfoBar")

        grid = QGridLayout(container)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)

        def _add(row: int, col: int, label: str, value: str, value_color: str | None = None):
            lbl = QLabel(f"{label}:")
            lbl.setStyleSheet(f"color: {colors['muted'].name()}; font-size: 14px; font-weight: 700;")
            val = QLabel(value)
            c = value_color or colors['text'].name()
            val.setStyleSheet(f"color: {c}; font-size: 15px; font-weight: 700;")
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(val, row, col * 2 + 1)

        _add(0, 0, "Model", data.model, colors['accent'].name())
        _add(0, 1, "Serial", data.serial, colors['accent'].name())
        _add(1, 0, "Customer", data.customer_name or "—")
        _add(1, 1, "Last Reported", data.last_reported)
        if data.unpacking_date:
            _add(2, 0, "Unpacking Date", data.unpacking_date, "#f77564")

        parent.addWidget(container)

    def _build_alerts(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        r = _corner_radii()

        # Mandatory alerts (red, always shown)
        for alert in data.mandatory_alerts:
            banner = QLabel(f"⛔  {alert}")
            banner.setWordWrap(True)
            banner.setStyleSheet(
                f"QLabel {{"
                f"  background-color: {colors['danger_bg'].name()};"
                f"  color: {colors['danger'].name()};"
                f"  border: 1px solid {colors['danger'].name()};"
                f"  border-radius: {r['md']}px;"
                f"  padding: 8px 12px;"
                f"  font-size: 12px;"
                f"  font-weight: 600;"
                f"}}"
            )
            parent.addWidget(banner)

        # Optional alerts (yellow, toggleable)
        for alert in data.optional_alerts:
            banner = QLabel(f"⚠  {alert}")
            banner.setWordWrap(True)
            banner.setStyleSheet(
                f"QLabel {{"
                f"  background-color: {colors['warning_bg'].name()};"
                f"  color: {colors['warning'].name()};"
                f"  border: 1px solid {colors['warning'].name()};"
                f"  border-radius: {r['md']}px;"
                f"  padding: 8px 12px;"
                f"  font-size: 12px;"
                f"  font-weight: 500;"
                f"}}"
            )
            parent.addWidget(banner)

    def _build_counters(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        counters = data.counters
        if not counters:
            return

        r = _corner_radii()

        row = QHBoxLayout()
        row.setSpacing(16)

        def _card(key: str, label: str) -> QWidget | None:
            val = counters.get(key)
            if val is None:
                return None
            w = QWidget()
            w.setObjectName("CounterCard")
            w.setFixedWidth(65)
            w.setStyleSheet(
                f"QWidget#CounterCard {{"
                f"  background-color: {colors['surface'].name()};"
                f"  border: 1px solid {colors['border'].name()};"
                f"  border-radius: {r['lg']}px;"
                f"  padding: 8px 10px;"
                f"}}"
            )
            vl = QVBoxLayout(w)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setSpacing(3)
            vl_lbl = QLabel(label)
            vl_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl_lbl.setStyleSheet(f"color: {colors['muted'].name()}; font-size: 9px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;")
            vl_val = QLabel(f"{val:,}" if isinstance(val, (int, float)) else str(val))
            vl_val.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl_val.setStyleSheet(f"color: {colors['text'].name()}; font-size: 16px; font-weight: 800;")
            vl.addWidget(vl_lbl)
            vl.addWidget(vl_val)
            return w

        for key, lbl in [("color", "Color"), ("black", "Black"), ("df", "DF"), ("total", "Total")]:
            card = _card(key, lbl)
            if card:
                row.addStretch()
                row.addWidget(card)
        row.addStretch()
        parent.addLayout(row)

    def _build_error_history(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        """Build the error history table between counters and wear analysis."""
        error_records = data.error_records
        r = _corner_radii()

        def _copy_error_history():
            headers = ["Code", "Counter", "Date", "Time"]
            rows = []
            for rec in error_records:
                rows.append([rec.code, rec.counter, rec.date, rec.time])
            _copy_tsv(headers, rows)

        if not error_records:
            none_lbl = QLabel("No error history available")
            none_lbl.setStyleSheet(
                f"color: {colors['muted'].name()}; font-size: 11px; padding: 4px 0;"
            )
            parent.addWidget(none_lbl)
            return

        # Container provides the rounded border; global theme handles scrollbar.
        # Border-radius capped at 6px (matches _scrollbar_radius cap in theme.py)
        # to prevent the scrollbar from visually collapsing at high corner strength.
        # QScrollBar:vertical gets a separate tiny border-radius (2px) so the
        # scrollbar track stays rounded even when the container's border-radius
        # clips child painting — this avoids the "flip to 90° corners" artifact.
        container = QWidget()
        container.setObjectName("ErrorHistoryCard")
        eh_radius = min(r['md'], 6)
        container.setStyleSheet(
            f"QWidget#ErrorHistoryCard {{"
            f"  background-color: {colors['surface'].name()};"
            f"  border: 1px solid {colors['border'].name()};"
            f"  border-radius: {eh_radius}px;"
            f"}}"
            f"QScrollBar:vertical {{"
            f"  border-radius: 2px;"
            f"}}"
        )
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Code", "Counter", "Date", "Time"])
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setFixedHeight(300)

        # Table is borderless — container provides the border + corner rounding.
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.horizontalHeader().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background-color: {colors['surface_high'].name()};"
            f"  color: {colors['muted'].name()};"
            f"  border: none;"
            f"  padding: 6px 8px;"
            f"  font-size: 11px;"
            f"  font-weight: 700;"
            f"}}"
        )

        table.setRowCount(len(error_records))
        for i, rec in enumerate(error_records):
            # Code
            code_item = QTableWidgetItem(rec.code)
            code_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            code_item.setForeground(colors['danger'])
            code_font = QFont()
            code_font.setBold(True)
            code_item.setFont(code_font)
            table.setItem(i, 0, code_item)

            # Counter
            counter_item = QTableWidgetItem(rec.counter)
            counter_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            counter_item.setForeground(colors['text'])
            table.setItem(i, 1, counter_item)

            # Date
            date_item = QTableWidgetItem(rec.date)
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            date_item.setForeground(colors['text'])
            table.setItem(i, 2, date_item)

            # Time
            time_item = QTableWidgetItem(rec.time)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setForeground(colors['muted'])
            table.setItem(i, 3, time_item)

            table.setRowHeight(i, 28)

        container_layout.addWidget(table)
        parent.addWidget(container)

    def _build_wear_table(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        r = _corner_radii()

        def _copy_wear():
            headers = ["Item", "Unit", "Wear %", "Status"]
            rows = []
            for f in data.findings:
                pct = (f.life_used or 0.0) * 100.0
                unit = f.kit_code if f.kit_code else "—"
                status = "DUE" if f.due else "OK"
                rows.append([f.canon, unit, f"{pct:.1f}%", status])
            _copy_tsv(headers, rows)

        parent.addWidget(_section_header("Wear Analysis", colors, _copy_wear))

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Item", "Unit", "Wear %", "", "Status"])
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 200)
        table.setColumnWidth(2, 70)
        table.setColumnWidth(3, 500)
        table.setColumnWidth(4, 65)

        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(False)
        table.setShowGrid(False)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setFixedHeight(len(data.findings) * 32 + 30)

        table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {colors['surface'].name()};"
            f"  border: 1px solid {colors['border'].name()};"
            f"  border-radius: {r['md']}px;"
            f"  gridline-color: transparent;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background-color: {colors['surface_high'].name()};"
            f"  color: {colors['muted'].name()};"
            f"  border: none;"
            f"  padding: 6px 8px;"
            f"  font-size: 11px;"
            f"  font-weight: 700;"
            f"}}"
        )

        items = data.findings
        table.setRowCount(len(items))
        for i, f in enumerate(items):
            canon_item = QTableWidgetItem(f.canon)
            canon_font = QFont()
            canon_font.setPointSize(10)
            canon_item.setFont(canon_font)
            canon_item.setForeground(colors['text'])
            pct = (f.life_used or 0.0) * 100.0
            table.setItem(i, 0, canon_item)

            # Unit
            unit_text = f.kit_code if f.kit_code else "—"
            unit_item = QTableWidgetItem(unit_text)
            unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            unit_item.setForeground(colors['muted'])
            table.setItem(i, 1, unit_item)

            # Wear %
            pct_item = QTableWidgetItem(f"{pct:.1f}%")
            pct_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if f.due:
                pct_item.setForeground(QColor("#e74c3c"))
            else:
                pct_item.setForeground(colors['text'])
            table.setItem(i, 2, pct_item)

            # Wear bar (centered vertically, preserves natural width)
            bar = _WearBar(pct, f.due, colors)
            bar_container = _CenterWidget(bar)
            table.setCellWidget(i, 3, bar_container)

            # Status badge (wrapped in a container for vertical centering)
            pill = _pill_label("DUE", "#e74c3c", "#ffffff") if f.due else _pill_label("OK", "#2ecc71", "#ffffff")
            container = QWidget()
            container.setStyleSheet("background: transparent;")
            vl = QVBoxLayout(container)
            vl.setContentsMargins(0, 0, 0, 0)
            vl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vl.addWidget(pill)
            table.setCellWidget(i, 4, container)

            table.setRowHeight(i, 32)

        parent.addWidget(table)

    def _build_final_parts(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        over = data.final_parts_over_100
        thr = data.final_parts_threshold

        if not over and not thr:
            return

        def _parts_table(entries, title: str):
            def _copy_parts():
                headers = ["Qty", "Part Number", "Unit"]
                rows = [[str(e.qty), e.part_number, e.unit] for e in entries]
                _copy_tsv(headers, rows)

            parent.addWidget(_section_header(title, colors, _copy_parts))
            if not entries:
                none_lbl = QLabel("(none)")
                none_lbl.setStyleSheet(f"color: {colors['muted'].name()}; font-size: 11px; padding: 4px 0;")
                parent.addWidget(none_lbl)
                return

            rp = _corner_radii()

            table = QTableWidget()
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["Qty", "Part Number", "Unit"])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, 35)
            table.setColumnWidth(2, 400)
            table.verticalHeader().setVisible(False)
            table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setShowGrid(False)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            table.setFixedHeight(len(entries) * 28 + 30)

            table.setStyleSheet(
                f"QTableWidget {{"
                f"  background-color: {colors['surface'].name()};"
                f"  border: 1px solid {colors['border'].name()};"
                f"  border-radius: {rp['md']}px;"
                f"}}"
                f"QHeaderView::section {{"
                f"  background-color: {colors['surface_high'].name()};"
                f"  color: {colors['muted'].name()};"
                f"  border: none;"
                f"  padding: 6px 8px;"
                f"  font-size: 11px;"
                f"  font-weight: 700;"
                f"}}"
            )

            table.setRowCount(len(entries))
            for i, e in enumerate(entries):
                qty_item = QTableWidgetItem(str(e.qty))
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                qty_item.setForeground(colors['text'])
                table.setItem(i, 0, qty_item)

                pn_item = QTableWidgetItem(e.part_number)
                pn_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                pn_item.setForeground(colors['accent'])
                table.setItem(i, 1, pn_item)

                unit_item = QTableWidgetItem(e.unit)
                unit_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                unit_item.setForeground(colors['muted'])
                table.setItem(i, 2, unit_item)

                table.setRowHeight(i, 28)

            parent.addWidget(table)

        _parts_table(over, "Final Parts — Over 100%")
        _parts_table(thr, "Final Parts — Threshold")

    def _build_summary_inline(self, parent: QVBoxLayout, data: SingleReportData, colors: dict) -> None:
        """Inline summary — no card background, plain text stats + donut chart."""

        def _stat_row(stat_label: str, stat_value: str):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(stat_label)
            lbl.setStyleSheet(f"color: {colors['muted'].name()}; font-size: 13px;")
            val = QLabel(stat_value)
            val.setStyleSheet(f"color: {colors['text'].name()}; font-size: 14px; font-weight: 700;")
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            return row

        parent.addLayout(_stat_row("Due items:", str(data.due_count)))
        parent.addLayout(_stat_row("Total items:", str(data.total_items)))
        parent.addLayout(_stat_row("Highest wear:", f"{data.highest_wear_pct:.1f}%"))
        thr_text = f"{data.threshold * 100:.1f}%" if data.threshold_enabled else "100%"
        parent.addLayout(_stat_row("Threshold:", thr_text))
        parent.addLayout(_stat_row("Basis:", data.life_basis.upper()))

        parent.addSpacing(8)

        # Donut chart
        donut = DonutChart()
        donut.set_data(data.due_count, data.ok_count, data.total_items, data.highest_wear_pct)
        donut.set_colors(
            due=QColor("#e74c3c"),
            ok=QColor("#2ecc71"),
            bg_ring=colors['border'],
            text=colors['text'],
            sub_text=colors['muted'],
        )
        donut.setFixedSize(160, 160)
        donut_wrapper = QHBoxLayout()
        donut_wrapper.addStretch()
        donut_wrapper.addWidget(donut)
        donut_wrapper.addStretch()
        parent.addLayout(donut_wrapper)
