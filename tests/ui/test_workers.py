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


def test_bulk_runner_normalizes_customer_map_keys(base_config):
    runner = BulkRunner(
        cfg=base_config,
        threshold=0.8,
        life_basis="page",
        customer_map={"inac67890": "Inactive Customer"},
    )

    assert runner.customer_map["INAC67890"] == "Inactive Customer"


def _ok_entry(serial: str, best_used: float) -> dict:
    """A minimal successful bulk result entry, pre-sorted by best_used."""
    return {
        "serial": serial,
        "model": "M",
        "best_used": best_used,
        "customer_name": "",
        "unpacking_date": None,
        # `report` doubles as a sentinel to identify which entry was written.
        "report": serial,
        "selection": None,
    }


def test_top_n_limits_individual_reports_to_top_n(monkeypatch):
    """Only the top-N serials (by usage) should get an individual PDF report."""
    cfg = BulkConfig(top_n=3, generate_pdfs=True)
    runner = BulkRunner(cfg=cfg, threshold=0.8, life_basis="page")

    # Pre-sorted by usage descending, exactly as run() supplies it.
    ok = [
        _ok_entry("S0", 0.9),
        _ok_entry("S1", 0.8),
        _ok_entry("S2", 0.7),
        _ok_entry("S3", 0.6),
        _ok_entry("S4", 0.5),
    ]

    written_reports: list = []
    monkeypatch.setattr(
        "pmgen.engine.single_report.create_pdf_report",
        lambda **kw: written_reports.append(kw["report"]),
    )

    written, top = runner._write_top_n_reports(
        ok, thr=0.8, basis="page", show_all=False, out_dir=".", thr_enabled=True
    )

    assert written == 3
    assert [t["serial"] for t in top] == ["S0", "S1", "S2"]
    assert written_reports == ["S0", "S1", "S2"]


def test_top_n_writes_all_when_fewer_serials_than_top_n(monkeypatch):
    cfg = BulkConfig(top_n=100, generate_pdfs=True)
    runner = BulkRunner(cfg=cfg, threshold=0.8, life_basis="page")

    ok = [_ok_entry("S0", 0.9), _ok_entry("S1", 0.8), _ok_entry("S2", 0.7)]

    count = {"n": 0}
    monkeypatch.setattr(
        "pmgen.engine.single_report.create_pdf_report",
        lambda **kw: count.__setitem__("n", count["n"] + 1),
    )

    written, top = runner._write_top_n_reports(
        ok, thr=0.8, basis="page", show_all=False, out_dir=".", thr_enabled=True
    )

    assert written == 3
    assert len(top) == 3
    assert count["n"] == 3


def test_top_n_continues_after_a_pdf_failure(monkeypatch):
    """A single PDF failure must not abort the remaining top-N reports."""
    cfg = BulkConfig(top_n=5, generate_pdfs=True)
    runner = BulkRunner(cfg=cfg, threshold=0.8, life_basis="page")

    ok = [_ok_entry(f"S{i}", 1.0 - i * 0.1) for i in range(5)]

    state = {"n": 0}

    def flaky(**kw):
        state["n"] += 1
        if state["n"] == 2:
            raise RuntimeError("boom")

    monkeypatch.setattr("pmgen.engine.single_report.create_pdf_report", flaky)

    written, top = runner._write_top_n_reports(
        ok, thr=0.8, basis="page", show_all=False, out_dir=".", thr_enabled=True
    )

    assert len(top) == 5  # top is still the full top-N slice
    assert written == 4   # 5 attempted, 1 failed