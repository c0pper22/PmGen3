from PyQt6.QtWidgets import QMainWindow, QToolButton

from pmgen.ui.factory import UIFactory


class _ToolbarWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.appearance_opened = False

    def _open_login_dialog(self):
        pass

    def _logout(self):
        pass

    def _open_due_threshold_dialog(self):
        pass

    def _open_life_basis_dialog(self):
        pass

    def _open_appearance_dialog(self):
        self.appearance_opened = True

    def _get_show_all(self):
        return False

    def _set_show_all(self, checked):
        pass

    def _get_colorized(self):
        return True

    def _set_colorized(self, checked):
        pass

    def _apply_colorized_highlighter(self):
        pass

    def _clear_output_window(self):
        pass

    def _show_about(self):
        pass

    def _open_catalog_editor(self):
        pass

    def _get_alerts_enabled(self):
        return True

    def _set_alerts_enabled(self, checked):
        pass

    def _start_bulk(self):
        pass

    def _open_bulk_settings(self):
        pass

    def _toggle_fullscreen(self, *args):
        pass

    def _confirm_exit(self):
        pass

    def _start_update_check(self, silent=False):
        pass


def test_settings_appearance_action_opens_dialog(qtbot):
    window = _ToolbarWindow()
    qtbot.addWidget(window)

    toolbar = UIFactory("").create_toolbar(window)

    settings_button = toolbar.findChild(QToolButton, "SettingsBtn")
    settings_menu = settings_button.menu()
    root_action_text = [action.text() for action in settings_menu.actions()]
    appearance_action = next(action for action in settings_menu.actions() if action.text() == "Appearance")

    assert appearance_action.menu() is None
    assert "Theme" not in root_action_text

    appearance_action.trigger()

    assert window.appearance_opened
