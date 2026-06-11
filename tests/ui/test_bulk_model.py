import pytest
from PyQt6.QtCore import Qt
from pmgen.ui.bulk_model import BulkQueueModel

def test_add_item(qtbot):
    """Test that adding an item correctly populates the internal data structure."""
    model = BulkQueueModel()
    
    model.add_item(serial="SN123", model="PrinterX", customer="CorpA", machine_status="Inactive")
    
    assert model.rowCount() == 1
    assert model.headerData(4, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "Machine State"
    
    assert model._data[0][0] == "SN123"
    assert model._data[0][1] == "PrinterX"
    assert model._data[0][3] == "Inactive"
    assert model._data[0][model._status_idx] == "Queued"

def test_update_status(qtbot):
    """Test that updating an item modifies the correct indices."""
    model = BulkQueueModel()
    model.add_item(serial="SN123")
    
    model.update_status(
        serial="SN123", 
        status="Done", 
        result="95.0%", 
        model="PrinterY",
        customer="CorpB",
        machine_status="Active"
    )
    
    assert model._data[0][model._status_idx] == "Done"
    assert model._data[0][model._result_idx] == "95.0%"
    assert model._data[0][1] == "PrinterY" 
    assert model._data[0][2] == "CorpB"
    assert model._data[0][3] == "Active"