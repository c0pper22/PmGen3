from dataclasses import fields

from PyQt6.QtWidgets import QMainWindow

from pmgen.ui.shell import TOP_BAR_HEIGHT, WindowControlSpec, build_frameless_top_bar, resolve_icon_dir


def test_window_control_spec_fields():
    assert [field.name for field in fields(WindowControlSpec)] == [
        "title",
        "icon_dir",
        "on_minimize",
        "on_toggle_fullscreen",
        "on_close",
        "show_update",
        "on_update",
    ]


def test_resolve_icon_dir_points_to_icons_folder():
    assert resolve_icon_dir().endswith("pmgen\\assets\\icons")


def test_build_frameless_top_bar_sets_controls(qtbot):
    window = QMainWindow()
    qtbot.addWidget(window)

    bar = build_frameless_top_bar(
        window,
        WindowControlSpec(
            title="Test",
            icon_dir=resolve_icon_dir(),
            on_minimize=window.showMinimized,
            on_toggle_fullscreen=lambda checked: None,
            on_close=window.close,
        ),
    )

    assert bar.objectName() == "TopBarBg"
    assert bar.height() == TOP_BAR_HEIGHT
    assert hasattr(window, "_act_full")
