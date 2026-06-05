import re

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
