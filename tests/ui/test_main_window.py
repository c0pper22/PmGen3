import pytest
from unittest.mock import MagicMock
from PyQt6.QtCore import Qt, QRegularExpression, QCoreApplication, QSettings
from PyQt6.QtWidgets import QWidget, QToolBar, QLabel, QComboBox, QVBoxLayout, QPlainTextEdit, QLineEdit, QPushButton
from PyQt6.QtGui import QStandardItemModel, QStandardItem

# Import the classes we want to test
from pmgen.ui.main_window import MainWindow, BulkRunTab
from pmgen.ui.bulk_run import BulkSortFilterProxyModel
from pmgen.ui.bulk_model import BulkQueueModel
from pmgen.ui.workers import BulkConfig

# =============================================================================
#  FIXTURES
# =============================================================================

@pytest.fixture(autouse=True)
def isolate_settings():
    """Isolates QSettings so tests do not overwrite actual user data."""
    QCoreApplication.setOrganizationName("PmGen_TestOrg")
    QCoreApplication.setApplicationName("PmGen_TestApp")
    settings = QSettings()
    settings.clear()
    yield
    settings.clear()

@pytest.fixture
def mock_main_window(qtbot, monkeypatch):
    """
    Safely creates a MainWindow by mocking out external dependencies and 
    injecting real dummy QWidgets so the Layouts don't throw TypeErrors.
    """
    class MockUIFactory:
        def __init__(self, *args, **kwargs): pass
        
        def create_secondary_bar(self, parent):
            parent.user_label = QLabel(parent)
            
            parent._id_combo = QComboBox(parent)
            parent._id_combo.setEditable(True)
            
            return QWidget(parent)
            
        def create_toolbar(self, parent):
            return QToolBar(parent)

    class MockInventoryTab(QWidget):
        def __init__(self, parent=None, *args, **kwargs):
            super().__init__(parent)
            self.model = MagicMock()
            self.model.get_dataframe.return_value = None
            
        def _get_cache_path(self):
            return "dummy_path"

    monkeypatch.setattr("pmgen.ui.main_window.UIFactory", MockUIFactory)
    monkeypatch.setattr("pmgen.ui.main_window.InventoryPage", MockInventoryTab)
    monkeypatch.setattr("pmgen.ui.main_window.QTimer.singleShot", MagicMock())

    window = MainWindow()
    # Mock tab_tools for closeEvent teardown
    window.tab_tools = MockInventoryTab(window)
    qtbot.addWidget(window)
    return window

# =============================================================================
#  TESTS: BulkSortFilterProxyModel
# =============================================================================

def test_proxy_model_filtering():
    """Test that the search filter correctly matches Serial, Model, or Customer."""
    source = BulkQueueModel()
    source.add_item(serial="SN123", model="PrinterX", customer="CorpA", machine_status="Active")
    source.add_item(serial="SN999", model="ScannerY", customer="CorpB", machine_status="Inactive")
    
    proxy = BulkSortFilterProxyModel()
    proxy.setSourceModel(source)
    
    proxy.setFilterRegularExpression(QRegularExpression("123"))
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 1)) == "SN123"

    proxy.setFilterRegularExpression(QRegularExpression("corpb"))
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 3)) == "CorpB"

    proxy.setFilterRegularExpression(QRegularExpression("inactive"))
    assert proxy.rowCount() == 1
    assert proxy.data(proxy.index(0, 4)) == "Inactive"

class MockBulkModel(QStandardItemModel):
    """A clean item model to bypass BulkQueueModel's complex internal logic for testing."""
    def __init__(self):
        super().__init__(0, 4)
        self.status_col = 1
        self.result_col = 2

    def add_test_row(self, serial, status, result, customer):
        row = [
            QStandardItem(serial),
            QStandardItem(status),
            QStandardItem(result),
            QStandardItem(customer)
        ]
        self.appendRow(row)


def test_bulk_run_tab_uses_normalized_customer_map_for_table(qtbot):
    tab = BulkRunTab(BulkConfig(), {"customer_map": {"inac67890": "Inactive Customer"}})
    qtbot.addWidget(tab)

    tab._on_item_updated("INAC67890", "Queued", "", "Unknown", "", "", "", "Inactive")

    assert tab.model._data[0][2] == "Inactive Customer"
    assert tab.model._data[0][3] == "Inactive"

def test_proxy_model_sorting_status():
    """Test that sorting by Status applies the custom priority order."""
    source = MockBulkModel()
    source.add_test_row("S1", "Queued", "", "")
    source.add_test_row("S2", "Done", "", "")
    source.add_test_row("S3", "Failed", "", "")
    source.add_test_row("S4", "Filtered", "", "")

    proxy = BulkSortFilterProxyModel()
    proxy.setSourceModel(source)
    
    proxy.sort(source.status_col, Qt.SortOrder.AscendingOrder)
    
    assert proxy.data(proxy.index(0, source.status_col)) == "Done"
    assert proxy.data(proxy.index(1, source.status_col)) == "Failed"
    assert proxy.data(proxy.index(2, source.status_col)) == "Filtered"
    assert proxy.data(proxy.index(3, source.status_col)) == "Queued"

def test_proxy_model_sorting_results():
    """Test that sorting by Results handles mixed floats, percentages, and strings."""
    source = MockBulkModel()
    source.add_test_row("S1", "", "—", "")
    source.add_test_row("S2", "", "10.5%", "")
    source.add_test_row("S3", "", "100.0%", "")
    source.add_test_row("S4", "", "5.0%", "")

    proxy = BulkSortFilterProxyModel()
    proxy.setSourceModel(source)
    
    proxy.sort(source.result_col, Qt.SortOrder.AscendingOrder)
    
    assert proxy.data(proxy.index(0, source.result_col)) == "—"
    assert proxy.data(proxy.index(1, source.result_col)) == "5.0%"
    assert proxy.data(proxy.index(2, source.result_col)) == "10.5%"
    assert proxy.data(proxy.index(3, source.result_col)) == "100.0%"

# =============================================================================
#  TESTS: MainWindow Settings & UI Logic
# =============================================================================

def test_mainwindow_bulk_config_save_load(mock_main_window):
    """Test that MainWindow correctly saves and loads bulk configuration to QSettings."""
    window = mock_main_window
    
    cfg = BulkConfig(
        top_n=50, 
        out_dir="C:/Test", 
        pool_size=8, 
        blacklist=["BAD_SN"], 
        custom_08_name="TestCol", 
        custom_08_code=123,
        machine_filter="inactive"
    )
    
    window._save_bulk_config(cfg)
    loaded_cfg = window._get_bulk_config()
    
    assert loaded_cfg.top_n == 50
    assert loaded_cfg.out_dir == "C:/Test"
    assert loaded_cfg.pool_size == 8
    assert "BAD_SN" in loaded_cfg.blacklist
    assert loaded_cfg.custom_08_name == "TestCol"
    assert loaded_cfg.custom_08_code == 123
    assert loaded_cfg.machine_filter == "inactive"


def test_mainwindow_bulk_config_defaults_machine_filter_to_both(mock_main_window):
    """Bulk machine filter should default to both for existing users."""
    window = mock_main_window

    loaded_cfg = window._get_bulk_config()

    assert loaded_cfg.machine_filter == "both"


def test_mainwindow_bulk_config_blacklist_roundtrip(mock_main_window):
    """Blacklist entries should round-trip correctly through save/load."""
    window = mock_main_window

    cfg = BulkConfig(
        blacklist=["ABC123", "XYZ789", "QWE*"],
        machine_filter="both",
    )
    window._save_bulk_config(cfg)
    loaded_cfg = window._get_bulk_config()

    assert loaded_cfg.blacklist == ["ABC123", "XYZ789", "QWE*"]
    assert len(loaded_cfg.blacklist) == 3


def test_mainwindow_bulk_config_blacklist_empty(mock_main_window):
    """Empty blacklist should save and load as empty list."""
    window = mock_main_window

    cfg = BulkConfig(blacklist=[], machine_filter="both")
    window._save_bulk_config(cfg)
    loaded_cfg = window._get_bulk_config()

    assert loaded_cfg.blacklist == []


def test_bulk_settings_tooltip_keys_are_complete():
    """Every bulk setting has a corresponding tooltip description."""
    from pmgen.ui.main_window import BULK_SETTINGS_TOOLTIPS

    expected = {
        "top_n", "pool_size", "machine_filter",
        "custom_08_name", "custom_08_code", "custom_08_sub",
        "custom_05_name", "custom_05_code", "custom_05_sub",
        "generate_pdfs", "output_dir", "blacklist",
        "unpack_min_age", "unpack_max_age",
    }
    assert set(BULK_SETTINGS_TOOLTIPS.keys()) == expected
    assert all(isinstance(v, str) and len(v) > 10 for v in BULK_SETTINGS_TOOLTIPS.values())


def test_mainwindow_tab_close_protection(mock_main_window, monkeypatch):
    """Test that the Home and Inventory tabs cannot be closed."""
    window = mock_main_window
    mock_remove = MagicMock()
    monkeypatch.setattr(window.tabs, "removeTab", mock_remove)
    
    # Try closing protected tabs
    window._on_tab_close_requested(0)
    window._on_tab_close_requested(1)
    
    mock_remove.assert_not_called()


def test_mainwindow_upsert_id_history_dedupes_and_caps(mock_main_window):
    """Serial history should be newest-first, de-duplicated, and capped to MAX_HISTORY."""
    window = mock_main_window

    for i in range(window.MAX_HISTORY + 5):
        window._upsert_id_history(f"sn{i}")

    assert window._id_combo.count() == window.MAX_HISTORY
    assert window._id_combo.itemText(0) == "SN29"
    assert window._id_combo.itemText(window._id_combo.count() - 1) == "SN5"

    window._upsert_id_history("sn10")
    assert window._id_combo.count() == window.MAX_HISTORY
    assert window._id_combo.itemText(0) == "SN10"


def test_generate_adds_serial_to_history_before_session_check(mock_main_window):
    """Generate click should populate dropdown history even if user is not signed in."""
    window = mock_main_window
    window._session = None

    window._id_combo.setEditText("ab123")
    window._on_generate_clicked()

    assert window._id_combo.count() == 1
    assert window._id_combo.itemText(0) == "AB123"


def test_manual_login_stores_authenticated_session(mock_main_window, monkeypatch):
    """Manual login should keep the authenticated session for report generation."""
    window = mock_main_window

    class FakeSession:
        pass

    fake_session = FakeSession()

    class DialogProbe(QWidget):
        def __init__(self, parent=None, *args, **kwargs):
            super().__init__(parent)
            self._content_layout = QVBoxLayout(self)
            self.accepted = False

        def exec(self):
            fields = self.findChildren(QLineEdit)
            fields[0].setText("tech.user")
            fields[1].setText("secret")
            buttons = self.findChildren(QPushButton)
            login_button = next(button for button in buttons if button.text() == "Login")
            login_button.click()
            return 0

        def accept(self):
            self.accepted = True

    save_credentials = MagicMock()
    login = MagicMock()

    monkeypatch.setattr("pmgen.ui.main_window.FramelessDialog", DialogProbe)
    monkeypatch.setattr("pmgen.ui.main_window.requests.Session", lambda: fake_session)
    monkeypatch.setattr("pmgen.io.http_client.save_credentials", save_credentials)
    monkeypatch.setattr("pmgen.io.http_client.login", login)
    monkeypatch.setattr("pmgen.ui.main_window.get_customer_map_after_login", lambda _session: {"ABCD12345": "Customer"})

    window._open_login_dialog()

    save_credentials.assert_called_once_with("tech.user", "secret")
    login.assert_called_once_with(fake_session)
    assert window._session is fake_session
    assert window._signed_in is True
    assert window._current_user == "tech.user"
    assert window.customerMap == {"ABCD12345": "Customer"}


def test_show_about_uses_db_models(mock_main_window, monkeypatch):
    """About dialog should source model count/list from CatalogDB."""
    window = mock_main_window

    class DialogProbe(QWidget):
        instances = []

        def __init__(self, parent=None, *args, **kwargs):
            super().__init__(parent)
            self._content_layout = QVBoxLayout(self)
            self.executed = False
            DialogProbe.instances.append(self)

        def exec(self):
            self.executed = True
            return 0

        def accept(self):
            pass

    class MockCatalogDB:
        def get_all_models(self):
            return ["Z900", "A100", "M500", "B200"]

    monkeypatch.setattr("pmgen.ui.main_window.FramelessDialog", DialogProbe)
    monkeypatch.setattr("pmgen.ui.main_window.CatalogDB", MockCatalogDB)

    window._show_about()

    dlg = DialogProbe.instances[-1]
    assert dlg.executed is True

    editors = dlg.findChildren(QPlainTextEdit)
    assert editors
    txt = editors[0].toPlainText()

    assert "Supported models: 4" in txt
    assert txt.index("A100") < txt.index("B200") < txt.index("M500") < txt.index("Z900")


def test_show_about_db_failure_shows_zero(mock_main_window, monkeypatch):
    """About dialog should still open and show zero models when DB read fails."""
    window = mock_main_window

    class DialogProbe(QWidget):
        instances = []

        def __init__(self, parent=None, *args, **kwargs):
            super().__init__(parent)
            self._content_layout = QVBoxLayout(self)
            self.executed = False
            DialogProbe.instances.append(self)

        def exec(self):
            self.executed = True
            return 0

        def accept(self):
            pass

    class FailingCatalogDB:
        def get_all_models(self):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr("pmgen.ui.main_window.FramelessDialog", DialogProbe)
    monkeypatch.setattr("pmgen.ui.main_window.CatalogDB", FailingCatalogDB)

    window._show_about()

    dlg = DialogProbe.instances[-1]
    assert dlg.executed is True

    editors = dlg.findChildren(QPlainTextEdit)
    assert editors
    txt = editors[0].toPlainText()

    assert "Supported models: 0" in txt


def test_open_appearance_dialog_toggles_theme_and_updates_button(mock_main_window, monkeypatch):
    window = mock_main_window

    class ThemeManagerProbe:
        def __init__(self):
            self.is_dark = True

        def toggle(self):
            self.is_dark = not self.is_dark

    class DialogProbe(QWidget):
        instances = []

        def __init__(self, parent=None, *args, **kwargs):
            super().__init__(parent)
            self._content_layout = QVBoxLayout(self)
            self.executed = False
            DialogProbe.instances.append(self)

        def exec(self):
            self.executed = True
            return 0

        def accept(self):
            pass

    window.theme_manager = ThemeManagerProbe()
    monkeypatch.setattr("pmgen.ui.main_window.FramelessDialog", DialogProbe)

    window._open_appearance_dialog()

    dlg = DialogProbe.instances[-1]
    theme_button = dlg.findChild(QPushButton, "ThemeToggleButton")

    assert dlg.executed is True
    assert theme_button.text() == "Switch to Light Mode"

    theme_button.click()

    assert window.theme_manager.is_dark is False
    assert theme_button.text() == "Switch to Dark Mode"


def test_open_catalog_editor_reuses_single_window(mock_main_window, monkeypatch):
    """Catalog editor window should be reused instead of recreated on repeated opens."""
    window = mock_main_window

    class MockCatalogEditorWindow(QWidget):
        instances = []

        def __init__(self, icon_dir, parent=None):
            super().__init__(parent)
            self.icon_dir = icon_dir
            MockCatalogEditorWindow.instances.append(self)

    monkeypatch.setattr("pmgen.ui.main_window.CatalogEditorWindow", MockCatalogEditorWindow)

    window._open_catalog_editor()
    first = window._catalog_editor_window

    window._open_catalog_editor()
    second = window._catalog_editor_window

    assert first is not None
    assert second is first
    assert len(MockCatalogEditorWindow.instances) == 1
