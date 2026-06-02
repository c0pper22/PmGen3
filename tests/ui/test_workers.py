import pytest
from datetime import date
from pmgen.ui.workers import BulkRunner, BulkConfig

@pytest.fixture
def base_config():
    """Provides a default config for our runner tests."""
    return BulkConfig()

def test_date_filter_too_old(base_config):
    """Test that a date older than the max threshold is flagged."""
    # Setup runner to exclude items older than 12 months
    runner = BulkRunner(
        cfg=base_config,
        threshold=0.8,
        life_basis="page",
        unpack_max_enabled=True,
        unpack_max_months=12
    )
    
    old_date = date(date.today().year - 5, 1, 1)
    
    result = runner._check_date_filter(old_date)
    assert result == "Too Old"

def test_date_filter_too_new(base_config):
    """Test that a date newer than the min threshold is flagged."""
    runner = BulkRunner(
        cfg=base_config,
        threshold=0.8,
        life_basis="page",
        unpack_min_enabled=True,
        unpack_min_months=6
    )
    
    new_date = date.today()
    
    result = runner._check_date_filter(new_date)
    assert result == "Too New"

def test_date_filter_passes(base_config):
    """Test that a valid date returns None."""
    # Enabled but with 0 months shouldn't flag today's date
    runner = BulkRunner(
        cfg=base_config,
        threshold=0.8,
        life_basis="page",
        unpack_max_enabled=True,
        unpack_max_months=120,
        unpack_min_enabled=True,
        unpack_min_months=0
    )
    
    result = runner._check_date_filter(date.today())
    assert result is None 


def test_bulk_config_defaults_machine_filter_to_both():
    cfg = BulkConfig()

    assert cfg.machine_filter == "both"


def test_bulk_runner_filters_machine_state(base_config):
    runner = BulkRunner(
        cfg=BulkConfig(machine_filter="inactive"),
        threshold=0.8,
        life_basis="page",
    )

    serials = runner._filter_serials_by_machine_state({
        "ACTV12345": "Active",
        "INAC67890": "Inactive",
    })

    assert serials == ["INAC67890"]