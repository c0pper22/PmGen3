"""Application design tokens, stylesheets, and runtime theme selection."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QSettings
from PyQt6.QtWidgets import QApplication

from .icons import refresh_themed_icons

# Surfaces
COLOR_SURFACE = "#e9edff"
COLOR_SURFACE_DIM = "#ccdaff"
COLOR_SURFACE_BRIGHT = "#faf9ff"
COLOR_SURFACE_LOWEST = "#ffffff"
COLOR_SURFACE_LOW = "#f1f3ff"
COLOR_SURFACE_HIGH = "#e1e8ff"
COLOR_SURFACE_HIGHEST = "#d8e2ff"
COLOR_BACKGROUND = "#faf9ff"
COLOR_SURFACE_VARIANT = "#d8e2ff"

# Content
COLOR_ON_SURFACE = "#051a3e"
COLOR_ON_SURFACE_VARIANT = "#434654"
COLOR_OUTLINE = "#737685"
COLOR_OUTLINE_VARIANT = "#c3c6d6"

# Primary brand
COLOR_PRIMARY = "#003d9b"
COLOR_ON_PRIMARY = "#ffffff"
COLOR_PRIMARY_CONTAINER = "#0052cc"
COLOR_ON_PRIMARY_CONTAINER = "#c4d2ff"
COLOR_INVERSE_PRIMARY = "#b2c5ff"
COLOR_SURFACE_TINT = "#0c56d0"
COLOR_PRIMARY_FIXED = "#dae2ff"
COLOR_PRIMARY_FIXED_DIM = "#b2c5ff"

# Secondary
COLOR_SECONDARY = "#535f73"
COLOR_ON_SECONDARY = "#ffffff"
COLOR_SECONDARY_CONTAINER = "#d4e0f8"
COLOR_ON_SECONDARY_CONTAINER = "#576377"

# Tertiary
COLOR_TERTIARY = "#7b2600"
COLOR_ON_TERTIARY = "#ffffff"
COLOR_TERTIARY_CONTAINER = "#a33500"
COLOR_ON_TERTIARY_CONTAINER = "#ffc6b2"

# Error / Danger
COLOR_ERROR = "#ba1a1a"
COLOR_ON_ERROR = "#ffffff"
COLOR_ERROR_CONTAINER = "#ffdad6"
COLOR_ON_ERROR_CONTAINER = "#93000a"

# Inverse
COLOR_INVERSE_SURFACE = "#1d3054"
COLOR_INVERSE_ON_SURFACE = "#edf0ff"

# Dark mode
DARK_BACKGROUND = "#0E1014"
DARK_SURFACE = "#171A20"
DARK_SURFACE_CONTAINER = "#20242C"
DARK_SURFACE_HIGH = "#2A2F38"
DARK_BORDER = "#303642"
DARK_OUTLINE = "#4A505C"
DARK_ON_SURFACE = "#F1F3F5"
DARK_ON_SURFACE_VARIANT = "#A7ADB7"
DARK_PRIMARY = "#b2c5ff"
DARK_PRIMARY_CONTAINER = "#0040a2"

# Semantic colors
COLOR_SUCCESS = "#1e7d4a"
COLOR_SUCCESS_BG = "#d1fae5"
COLOR_WARNING = "#b45309"
COLOR_WARNING_BG = "#fef3c7"
COLOR_DANGER = "#ba1a1a"
COLOR_DANGER_BG = "#ffdad6"

# Typography
FONT_HEADING = "Hanken Grotesk"
FONT_BODY = "Inter"
_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"
_COMBO_DOWN_DARK = _ICON_DIR / "combo-down-dark.svg"
_COMBO_DOWN_LIGHT = _ICON_DIR / "combo-down-light.svg"
_SPIN_UP_DARK = _ICON_DIR / "up-dark.svg"
_SPIN_UP_LIGHT = _ICON_DIR / "up-light.svg"
_SPIN_DOWN_DARK = _ICON_DIR / "down-dark.svg"
_SPIN_DOWN_LIGHT = _ICON_DIR / "down-light.svg"
TYPO_HEADLINE_LG = (24, 600, 32, 0.00)
TYPO_HEADLINE_MD = (20, 600, 28, 0.00)
TYPO_HEADLINE_SM = (16, 600, 24, 0.00)
TYPO_BODY_LG = (15, 400, 22, 0.00)
TYPO_BODY_MD = (14, 400, 20, 0.00)
TYPO_BODY_SM = (13, 400, 18, 0.00)
TYPO_LABEL_MD = (12, 600, 16, 0.05)
TYPO_LABEL_SM = (11, 500, 14, 0.00)

# Spacing
SPACING_UNIT = 4
SPACING_XS = 4
SPACING_SM = 8
SPACING_MD = 16
SPACING_LG = 24
SPACING_XL = 32
SPACING_CONTAINER_MARGIN = 24
SPACING_GUTTER = 16

# Radius
RADIUS_NONE = 0
RADIUS_SM = 2
RADIUS_DEFAULT = 4
RADIUS_MD = 6
RADIUS_LG = 8
RADIUS_XL = 12
RADIUS_FULL = 9999

CORNER_ROUNDNESS_KEY = "ui/corner_roundness"
CORNER_ROUNDNESS_DEFAULT = 50
CORNER_ROUNDNESS_MIN = 0
CORNER_ROUNDNESS_MAX = 100


def _clamp_corner_strength(value: int) -> int:
    return max(CORNER_ROUNDNESS_MIN, min(CORNER_ROUNDNESS_MAX, int(value)))


def _corner_scale(value: int) -> float:
    strength = _clamp_corner_strength(value)
    # 50 preserves the existing radius tokens; 100 doubles them.
    return strength / 50.0


def _scaled_radius(base: int, scale: float) -> int:
    if base <= 0 or scale <= 0.0:
        return 0
    return max(1, int(round(base * scale)))


def _badge_radius(scale: float) -> int:
    # Qt can render tiny badges as square when radius grows too large for height.
    return min(_scaled_radius(RADIUS_LG, scale), 10)


def _popup_radius(scale: float) -> int:
    # Keep popups clearly rounded, but avoid oversized corners that look distorted.
    return min(_scaled_radius(RADIUS_DEFAULT, scale), 10)

OUTPUT_HIGHLIGHT_COLORS = {
    "normal": COLOR_ON_PRIMARY,
    "muted": DARK_ON_SURFACE_VARIANT,
    "header": DARK_PRIMARY,
    "rule": DARK_OUTLINE,
    "info": COLOR_WARNING,
    "label": COLOR_ON_PRIMARY_CONTAINER,
    "alert": COLOR_ERROR,
    "customer_value": "#bb97fd",
    "bulk": "#a680eb",
    "bulk_serial": "#ffff55",
    "bulk_ok": "#00ff3c",
    "bulk_filtered": COLOR_DANGER,
    "pct_low": "#40ed68",
    "pct_mid": "#f79346",
    "pct_high": COLOR_DANGER,
    "kit_row": "#a6da95",
    "due_bullet": "#f7768e",
    "due_row_base": "#bbbbbb",
    "due_canon": "#1c94d5",
    "due_pct": "#e0af68",
    "due_flag": "#f7768e",
    "model_value": "#a6da95",
    "serial_value": "#7dcfff",
    "report_date": "#e0af68",
    "unpacking_date": "#f77564",
    "badge_line_base": "#bfbfbf",
    "threshold_value": "#fb7127",
    "basis_badge": "#fb7127",
    "counters_base": "#bfbfbf",
    "kv_label": "#1c94d5",
    "kv_value": "#e0af68",
}


def _qss(
    *,
    bg: str,
    surface: str,
    surface_low: str,
    surface_high: str,
    text: str,
    muted: str,
    border: str,
    subtle_border: str,
    primary: str,
    primary_text: str,
    primary_hover: str,
    danger: str,
    danger_bg: str,
    combo_arrow: Path,
    spin_up_arrow: Path,
    spin_down_arrow: Path,
    radius_sm: int,
    radius_default: int,
    radius_lg: int,
    radius_popup: int,
    radius_badge: int,
    radius_full: int,
) -> str:
    combo_arrow_url = combo_arrow.as_posix()
    spin_up_arrow_url = spin_up_arrow.as_posix()
    spin_down_arrow_url = spin_down_arrow.as_posix()
    return f"""
QMainWindow, QDialog, QWidget {{
    background: {bg};
    color: {text};
    font-family: "{FONT_BODY}", "Segoe UI", sans-serif;
    font-size: {TYPO_BODY_MD[0]}px;
}}

QLabel {{ color: {text}; background: transparent; }}
QLabel[class="muted"], QLabel#DialogLabel {{ color: {muted}; }}
QLabel[class="success-label"] {{ color: {COLOR_SUCCESS}; font-weight: 700; }}
QLabel[class="status-chip"], QLabel#ThresholdBadge, QLabel#BasisBadge {{
    color: {muted};
    background: {surface_high};
    border: 1px solid {subtle_border};
    border-radius: {radius_badge}px;
    padding: {SPACING_XS}px {SPACING_SM}px;
    font-size: {TYPO_LABEL_SM[0]}px;
    font-weight: {TYPO_LABEL_SM[1]};
}}
QLabel[class="headline-sm"] {{
    color: {text};
    font-family: "{FONT_HEADING}", "Segoe UI", sans-serif;
    font-size: {TYPO_HEADLINE_SM[0]}px;
    font-weight: {TYPO_HEADLINE_SM[1]};
}}
QLabel[class="warning-banner"] {{
    color: {COLOR_WARNING};
    background: {COLOR_WARNING_BG};
    border: 1px solid {COLOR_WARNING};
    border-radius: {radius_lg}px;
    padding: {SPACING_SM}px {SPACING_MD}px;
}}

QToolBar {{
    background: {surface};
    border: none;
    spacing: 0px;
    padding: 0px;
}}
#TopBarBg {{
    background: {surface};
    border-bottom: 1px solid {border};
}}
#TopBarNav, #TopBarControls, #TopBarDragRegion {{
    background: transparent;
}}
QLabel#TitleLabel {{
    color: {text};
    font-family: "{FONT_HEADING}", "Segoe UI", sans-serif;
    font-size: {TYPO_HEADLINE_SM[0]}px;
    font-weight: {TYPO_HEADLINE_SM[1]};
}}
QToolButton {{
    border: none;
    background: transparent;
    color: {text};
    padding: {SPACING_SM}px {SPACING_MD}px;
    border-radius: {radius_default}px;
}}
QToolButton:hover {{ background-color: {surface_high}; }}
QToolButton#SettingsBtn, QToolButton#BulkBtn {{
    font-weight: 600;
    min-height: 32px;
    padding: {SPACING_SM}px {SPACING_MD}px;
}}
QToolButton#SettingsBtn::menu-indicator, QToolButton#BulkBtn::menu-indicator {{
    image: none;
    width: 0px;
}}
QMenu {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius_popup}px;
    padding: 4px;
}}
QMenu::item {{
    padding: {SPACING_SM}px {SPACING_LG}px;
    border-radius: {radius_sm}px;
    margin: 1px 2px;
}}
QMenu::item:selected {{ background: {surface_high}; }}
QMenu::separator {{
    height: 1px;
    background: {subtle_border};
    margin: 4px 8px;
}}

QPushButton {{
    padding: {SPACING_SM}px {SPACING_MD}px;
    border-radius: {radius_default}px;
    border: 1px solid {subtle_border};
    background: {surface_low};
    color: {text};
    font-weight: {TYPO_LABEL_MD[1]};
}}
QPushButton:hover {{ background: {surface_high}; }}
QPushButton[class="primary"], QPushButton#GenerateBtn {{
    background: {primary};
    border-color: {primary};
    color: {primary_text};
}}
QPushButton[class="primary"]:hover, QPushButton#GenerateBtn:hover {{
    background: {primary_hover};
    border-color: {primary_hover};
}}
QPushButton[class="secondary"], QPushButton#BulkExportBtn {{
    background: {surface_low};
    border-color: {subtle_border};
}}
QPushButton[class="danger"], QPushButton#BulkStopBtn {{
    background: {danger_bg};
    border-color: {danger};
    color: {danger};
}}
QPushButton:disabled {{
    color: {muted};
    background: {surface_high};
    border-color: {subtle_border};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{
    background: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    border-radius: {radius_sm}px;
    selection-background-color: {primary};
    selection-color: {primary_text};
    padding: {SPACING_SM}px;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QListWidget:focus {{
    border: 2px solid {primary};
}}
QComboBox::drop-down {{
    border-left: 1px solid {subtle_border};
    width: 24px;
}}
QComboBox::down-arrow {{
    image: url("{combo_arrow_url}");
    width: 10px;
    height: 6px;
}}
QComboBox#IdInput QLineEdit {{
    padding-right: 28px;
}}
QSpinBox, QDoubleSpinBox {{
    padding-right: 28px;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {subtle_border};
    border-bottom: 1px solid {subtle_border};
    border-top-right-radius: {radius_sm}px;
    background: transparent;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border-left: 1px solid {subtle_border};
    border-bottom-right-radius: {radius_sm}px;
    background: transparent;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {surface_high};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url("{spin_up_arrow_url}");
    width: 10px;
    height: 6px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url("{spin_down_arrow_url}");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView, #IdCompleterPopup {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius_popup}px;
    padding: 2px;
    outline: 0;
    selection-background-color: {primary};
    selection-color: {primary_text};
}}
QComboBox QAbstractItemView::item, #IdCompleterPopup::item {{
    margin: 1px 2px;
    border-radius: {radius_sm}px;
    padding: {SPACING_SM}px {SPACING_MD}px;
}}
QCheckBox {{ color: {text}; spacing: {SPACING_SM}px; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {subtle_border};
    border-radius: {radius_sm}px;
    background: {surface_low};
}}
QCheckBox::indicator:checked {{ background: {primary}; border-color: {primary}; }}
QSlider#ThresholdSlider::groove:horizontal {{
    border: 1px solid {subtle_border};
    background: {surface_high};
    height: 8px;
    border-radius: {radius_sm}px;
}}
QSlider#ThresholdSlider::handle:horizontal {{
    background: {primary};
    border: 1px solid {primary};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: {radius_full}px;
}}
QSlider#ThresholdSlider::sub-page:horizontal {{ background: {primary}; }}

QProgressBar#ProgressBar {{
    border: 1px solid {subtle_border};
    background: {surface_high};
    color: {text};
    text-align: center;
    border-radius: {radius_full}px;
}}
QProgressBar#ProgressBar::chunk {{
    background-color: {primary};
    border-radius: {radius_full}px;
}}

QTabWidget::pane {{
    border: 1px solid {subtle_border};
    background: {bg};
    border-radius: {radius_lg}px;
    margin-top: -1px;
}}
QTabWidget::tab-bar {{ alignment: left; }}
QTabBar::tab {{
    background: {surface};
    color: {muted};
    padding: {SPACING_SM}px {SPACING_LG}px;
    border: 1px solid {subtle_border};
    border-bottom: none;
    border-top-left-radius: {radius_default}px;
    border-top-right-radius: {radius_default}px;
    margin-right: {SPACING_XS}px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {surface_low};
    color: {text};
}}
QTabBar::tab:hover:!selected {{ background: {surface_high}; color: {text}; }}

QTableView, QTableWidget {{
    background-color: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    border-radius: {radius_lg}px;
    gridline-color: {subtle_border};
    selection-background-color: {primary};
    selection-color: {primary_text};
    alternate-background-color: {surface};
}}
QHeaderView::section {{
    background-color: {surface};
    color: {text};
    padding: {SPACING_SM}px;
    border: none;
    border-bottom: 1px solid {subtle_border};
    font-size: {TYPO_LABEL_MD[0]}px;
    font-weight: {TYPO_LABEL_MD[1]};
}}
QTableCornerButton::section {{
    background-color: {surface};
    border: 1px solid {subtle_border};
}}
QSplitter::handle {{ background: {bg}; }}
QScrollBar:vertical {{
    border-left: 1px solid {subtle_border};
    background: {surface};
    width: 14px;
    margin: 0px;
}}
QScrollBar::handle:vertical {{
    background: {border};
    min-height: 20px;
    border-radius: {radius_default}px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {primary}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

#SecondaryBar {{
    background: {surface_low};
    border: 1px solid {subtle_border};
    border-radius: {radius_lg}px;
    padding: {SPACING_LG}px;
}}
#MainEditor {{
    background: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    border-radius: {radius_lg}px;
    font-family: Consolas, "Fira Code", monospace;
    font-size: {TYPO_BODY_SM[0]}px;
}}
#MainEditor:focus {{ border: 2px solid {primary}; }}
#IdInput {{
    background: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    border-radius: {radius_sm}px;
    padding: {SPACING_SM}px {SPACING_MD}px;
    font-weight: 700;
}}
#IdInput:focus {{ border: 2px solid {primary}; }}
#BulkSearch {{
    background: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    border-radius: {radius_sm}px;
    padding: {SPACING_SM}px {SPACING_MD}px;
    font-size: {TYPO_BODY_SM[0]}px;
}}
#BulkSearch:focus {{ border: 2px solid {primary}; }}
#BulkRunHeader, #InventoryToolbar, #Card, QWidget[class="card"] {{
    background: {surface_low};
    border: 1px solid {subtle_border};
    border-radius: {radius_lg}px;
}}

QDialog#FramelessDialogRoot {{
    background: transparent;
    border: none;
}}
#FramelessDialogFrame {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {radius_lg}px;
}}
#DialogTitleBar {{
    background: {surface};
    border-top-left-radius: {radius_lg}px;
    border-top-right-radius: {radius_lg}px;
}}
#DialogTitleBar #DialogBtnGroup {{
    background: transparent;
    border: none;
}}
#DialogContent {{
    background: {surface};
    border-left: 1px solid {border};
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
    border-bottom-left-radius: {radius_lg}px;
    border-bottom-right-radius: {radius_lg}px;
}}
#DialogTitleLabel {{
    color: {text};
    font-weight: 600;
}}
#DialogSection {{
    background: {surface_low};
    border: 1px solid {subtle_border};
    border-radius: {radius_lg}px;
}}
#DialogSectionTitle {{
    color: {text};
    font-weight: 700;
}}
#DialogFormLabel {{
    color: {muted};
}}
#DialogBtn {{
    padding: {SPACING_XS}px;
    border-radius: {radius_default}px;
}}
#DialogTitleBar QToolButton#DialogBtn {{
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
    padding: 0px;
    border: none;
    border-radius: {radius_default}px;
    background: transparent;
}}
#DialogTitleBar QToolButton#DialogBtn:hover {{
    background: {surface_high};
}}
#DialogTitleBar QToolButton#DialogBtn:pressed {{
    background: {surface_low};
}}
#TopBarControls QToolButton#DialogBtn {{
    min-width: 36px;
    min-height: 36px;
    max-width: 36px;
    max-height: 36px;
}}
#DialogSeparator {{
    background: {subtle_border};
    max-height: 1px;
    min-height: 1px;
}}
#DialogInput {{
    background: {surface_low};
    color: {text};
    border: 1px solid {subtle_border};
    font-weight: 700;
}}
#DialogInput:focus {{ border: 2px solid {primary}; }}
#DialogCheckbox {{ background: transparent; }}
#UserLabel {{
    background: transparent;
    color: {text};
    font-weight: 700;
}}
"""


def _radii_for_strength(corner_strength: int) -> tuple[int, int, int, int, int, int]:
    scale = _corner_scale(corner_strength)
    return (
        _scaled_radius(RADIUS_SM, scale),
        _scaled_radius(RADIUS_DEFAULT, scale),
        _scaled_radius(RADIUS_LG, scale),
        _popup_radius(scale),
        _badge_radius(scale),
        RADIUS_FULL,
    )


def _build_light_qss(corner_strength: int) -> str:
    radius_sm, radius_default, radius_lg, radius_popup, radius_badge, radius_full = _radii_for_strength(corner_strength)
    return _qss(
        bg=COLOR_BACKGROUND,
        surface=COLOR_SURFACE_LOWEST,
        surface_low=COLOR_SURFACE_LOWEST,
        surface_high=COLOR_SURFACE_HIGH,
        text=COLOR_ON_SURFACE,
        muted=COLOR_ON_SURFACE_VARIANT,
        border=COLOR_OUTLINE,
        subtle_border=COLOR_OUTLINE_VARIANT,
        primary=COLOR_PRIMARY,
        primary_text=COLOR_ON_PRIMARY,
        primary_hover=COLOR_PRIMARY_CONTAINER,
        danger=COLOR_DANGER,
        danger_bg=COLOR_DANGER_BG,
        combo_arrow=_COMBO_DOWN_LIGHT,
        spin_up_arrow=_SPIN_UP_LIGHT,
        spin_down_arrow=_SPIN_DOWN_LIGHT,
        radius_sm=radius_sm,
        radius_default=radius_default,
        radius_lg=radius_lg,
        radius_popup=radius_popup,
        radius_badge=radius_badge,
        radius_full=radius_full,
    )


def _build_dark_qss(corner_strength: int) -> str:
    radius_sm, radius_default, radius_lg, radius_popup, radius_badge, radius_full = _radii_for_strength(corner_strength)
    return _qss(
        bg=DARK_BACKGROUND,
        surface=DARK_SURFACE,
        surface_low=DARK_SURFACE_CONTAINER,
        surface_high=DARK_SURFACE_HIGH,
        text=DARK_ON_SURFACE,
        muted=DARK_ON_SURFACE_VARIANT,
        border=DARK_BORDER,
        subtle_border=DARK_OUTLINE,
        primary=DARK_PRIMARY_CONTAINER,
        primary_text=COLOR_ON_PRIMARY,
        primary_hover=COLOR_PRIMARY_CONTAINER,
        danger=COLOR_DANGER,
        danger_bg=DARK_SURFACE_HIGH,
        combo_arrow=_COMBO_DOWN_DARK,
        spin_up_arrow=_SPIN_UP_DARK,
        spin_down_arrow=_SPIN_DOWN_DARK,
        radius_sm=radius_sm,
        radius_default=radius_default,
        radius_lg=radius_lg,
        radius_popup=radius_popup,
        radius_badge=radius_badge,
        radius_full=radius_full,
    )


LIGHT_QSS = _build_light_qss(CORNER_ROUNDNESS_DEFAULT)
DARK_QSS = _build_dark_qss(CORNER_ROUNDNESS_DEFAULT)

GLOBAL_STYLE_DARK = DARK_QSS


class ThemeManager(QObject):
    def __init__(self, app: QApplication):
        super().__init__(app)
        self._app = app
        self._is_dark = True

    @property
    def is_dark(self) -> bool:
        return self._is_dark

    def save_mode(self, mode: str) -> None:
        if mode in {"dark", "light"}:
            QSettings().setValue("ui/theme_mode", mode)

    def _get_corner_strength(self) -> int:
        try:
            value = int(QSettings().value(CORNER_ROUNDNESS_KEY, CORNER_ROUNDNESS_DEFAULT, int))
        except (TypeError, ValueError):
            value = CORNER_ROUNDNESS_DEFAULT
        return _clamp_corner_strength(value)

    def _apply_mode(self, mode: str, *, save: bool) -> None:
        corner_strength = self._get_corner_strength()
        self._app.setStyle("Fusion")
        if mode == "light":
            self._app.setStyleSheet(_build_light_qss(corner_strength))
            self._is_dark = False
            self._app.setProperty("pmgenThemeMode", "light")
            refresh_themed_icons(self._app, self._is_dark)
            if save:
                self.save_mode("light")
            return

        self._app.setStyleSheet(_build_dark_qss(corner_strength))
        self._is_dark = True
        self._app.setProperty("pmgenThemeMode", "dark")
        refresh_themed_icons(self._app, self._is_dark)
        if save:
            self.save_mode("dark")

    def apply_light(self) -> None:
        self._apply_mode("light", save=True)

    def apply_dark(self) -> None:
        self._apply_mode("dark", save=True)

    def reapply(self) -> None:
        self._apply_mode("dark" if self._is_dark else "light", save=False)

    def toggle(self) -> None:
        if self._is_dark:
            self.apply_light()
        else:
            self.apply_dark()

    def apply_saved(self) -> None:
        mode = QSettings().value("ui/theme_mode", "dark", str)
        self._apply_mode("light" if mode == "light" else "dark", save=False)


def apply_static_theme(app: QApplication) -> ThemeManager:
    theme_manager = ThemeManager(app)
    theme_manager.apply_saved()
    return theme_manager
