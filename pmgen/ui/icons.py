"""Theme-aware icon helpers for local SVG assets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QAbstractButton, QApplication

_DEFAULT_ICON_DIR = Path(__file__).resolve().parents[1] / "assets" / "icons"


def default_icon_dir() -> Path:
    return _DEFAULT_ICON_DIR


def _theme_suffix(is_dark: bool | None = None) -> str:
    if is_dark is None:
        app = QApplication.instance()
        is_dark = bool(app and app.property("pmgenThemeMode") == "dark")
    return "dark" if is_dark else "light"


def themed_icon_path(
    icon_name: str,
    icon_dir: str | Path | None = None,
    is_dark: bool | None = None,
    role: str | None = None,
) -> Path:
    base = Path(icon_dir) if icon_dir else _DEFAULT_ICON_DIR
    suffix = _theme_suffix(is_dark)
    candidates = []
    if role:
        candidates.extend([
            base / f"{icon_name}-{role}-{suffix}.svg",
            base / f"{icon_name}-{role}.svg",
        ])
    candidates.extend([
        base / f"{icon_name}-{suffix}.svg",
        base / f"{icon_name}.svg",
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return base / f"{icon_name}.svg"


def set_themed_icon(
    target: QAction | QAbstractButton,
    icon_name: str,
    icon_dir: str | Path | None = None,
    is_dark: bool | None = None,
    role: str | None = None,
) -> None:
    icon_path = themed_icon_path(icon_name, icon_dir, is_dark, role)
    target.setProperty("pmgenIconName", icon_name)
    target.setProperty("pmgenIconDir", str(icon_dir or _DEFAULT_ICON_DIR))
    target.setProperty("pmgenIconRole", role or "")
    target.setProperty("pmgenResolvedIconPath", str(icon_path))
    target.setIcon(QIcon(str(icon_path)))


def _themed_icon_targets(app: QApplication) -> Iterable[QAction | QAbstractButton]:
    for widget in app.allWidgets():
        if isinstance(widget, QAbstractButton) and widget.property("pmgenIconName"):
            yield widget
        for action in widget.findChildren(QAction):
            if action.property("pmgenIconName"):
                yield action


def refresh_themed_icons(app: QApplication, is_dark: bool) -> None:
    for target in _themed_icon_targets(app):
        icon_name = target.property("pmgenIconName")
        icon_dir = target.property("pmgenIconDir")
        role = target.property("pmgenIconRole") or None
        if icon_name:
            set_themed_icon(target, str(icon_name), icon_dir, is_dark, str(role) if role else None)
