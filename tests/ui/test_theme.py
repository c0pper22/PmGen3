import re
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QSettings
from PyQt6.QtWidgets import QApplication

from pmgen.ui import theme
from pmgen.ui.theme import DARK_QSS, LIGHT_QSS, ThemeManager, apply_static_theme


def _isolate_settings():
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "C:/tmp/pmgen-test-settings")
    QCoreApplication.setOrganizationName("PmGen_TestOrg")
    QCoreApplication.setApplicationName("PmGen_TestApp")
    QSettings().clear()


def test_apply_static_theme_returns_manager_and_defaults_dark(qtbot):
    _isolate_settings()
    QSettings().clear()
    manager = apply_static_theme(QApplication.instance())

    assert isinstance(manager, ThemeManager)
    assert manager.is_dark
    assert QApplication.instance().styleSheet() == DARK_QSS


def test_saved_light_mode_and_toggle(qtbot):
    _isolate_settings()
    settings = QSettings()
    settings.clear()
    settings.setValue("ui/theme_mode", "light")

    manager = apply_static_theme(QApplication.instance())

    assert not manager.is_dark
    assert QApplication.instance().styleSheet() == LIGHT_QSS

    manager.toggle()

    assert manager.is_dark
    assert settings.value("ui/theme_mode", "", str) == "dark"


def test_qss_bodies_do_not_define_raw_hex_literals():
    source = open(theme.__file__, encoding="utf-8").read()
    qss_source = source[source.index("def _qss("):source.index("LIGHT_QSS = _qss")]

    assert not re.search(r"#[0-9A-Fa-f]{3,6}", qss_source)


def test_combo_box_theme_arrows_are_defined():
    icon_dir = Path(theme.__file__).resolve().parents[1] / "assets" / "icons"

    assert (icon_dir / "combo-down-dark.svg").exists()
    assert (icon_dir / "combo-down-light.svg").exists()
    assert "combo-down-dark.svg" in DARK_QSS
    assert "combo-down-light.svg" in LIGHT_QSS


def test_spin_box_theme_arrows_are_defined():
    icon_dir = Path(theme.__file__).resolve().parents[1] / "assets" / "icons"

    assert (icon_dir / "up-dark.svg").exists()
    assert (icon_dir / "up-light.svg").exists()
    assert (icon_dir / "down-dark.svg").exists()
    assert (icon_dir / "down-light.svg").exists()
    assert "up-dark.svg" in DARK_QSS
    assert "down-dark.svg" in DARK_QSS
    assert "up-light.svg" in LIGHT_QSS
    assert "down-light.svg" in LIGHT_QSS
