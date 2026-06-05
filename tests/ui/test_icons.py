from pathlib import Path

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QToolButton

from pmgen.ui import icons


def _pixmap_has_ink(icon: QIcon) -> bool:
    image = icon.pixmap(QSize(24, 24)).toImage()
    for x in range(image.width()):
        for y in range(image.height()):
            if image.pixelColor(x, y).alpha() > 0:
                return True
    return False


def test_all_svg_icons_load_and_render_pixels(qtbot):
    icon_dir = icons.default_icon_dir()

    for path in icon_dir.glob("*.svg"):
        icon = QIcon(str(path))

        assert not icon.isNull(), path.name
        assert _pixmap_has_ink(icon), path.name


def test_themed_icon_helper_switches_default_variants(qtbot):
    icon_dir = icons.default_icon_dir()
    button = QToolButton()
    qtbot.addWidget(button)

    icons.set_themed_icon(button, "minimize", icon_dir, is_dark=True)

    assert Path(button.property("pmgenResolvedIconPath")).name == "minimize-dark.svg"

    icons.refresh_themed_icons(QApplication.instance(), is_dark=False)

    assert Path(button.property("pmgenResolvedIconPath")).name == "minimize-light.svg"
    assert not button.icon().isNull()


def test_themed_icon_helper_supports_button_roles(qtbot):
    icon_dir = icons.default_icon_dir()
    button = QToolButton()
    qtbot.addWidget(button)

    icons.set_themed_icon(button, "import", icon_dir, is_dark=False, role="primary")

    assert Path(button.property("pmgenResolvedIconPath")).name == "import-primary.svg"

    icons.set_themed_icon(button, "delete", icon_dir, is_dark=True, role="danger")

    assert Path(button.property("pmgenResolvedIconPath")).name == "delete-danger-dark.svg"
