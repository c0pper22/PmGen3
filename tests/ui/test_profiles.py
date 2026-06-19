"""Tests for pmgen.ui.profile_store — profile persistence for Bulk Settings."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings

from pmgen.ui.workers import BulkConfig
from pmgen.ui.profile_store import (
    DEFAULT_PROFILE_NAME,
    list_profile_names,
    load_profile,
    save_profile,
    delete_profile,
    get_last_profile_name,
    set_last_profile_name,
)

# Each test uses a unique organisation/app name so QSettings don't collide.
_TEST_ORG = "PmGenTest"
_TEST_APP = "TestProfiles"


@pytest.fixture(autouse=True)
def _isolated_qsettings(monkeypatch):
    """Point QSettings at a unique scope per-test, using a singleton instance."""
    s = QSettings(_TEST_ORG, _TEST_APP)
    s.clear()
    s.sync()
    # Patch the QSettings reference INSIDE profile_store so that the
    # already-imported module uses our test instance rather than the real one.
    monkeypatch.setattr("pmgen.ui.profile_store.QSettings", lambda *_args, **_kwargs: s)


def _sample_config(**overrides) -> BulkConfig:
    """Return a BulkConfig with every field set to a non-default value."""
    kwargs = dict(
        top_n=50,
        out_dir="C:\\Test\\Out",
        pool_size=8,
        blacklist=["ABC123", "DEF456"],
        custom_08_name="Adjust",
        custom_08_code=2405,
        custom_08_sub=2,
        custom_05_name="Value",
        custom_05_code=2731,
        custom_05_sub=1,
        generate_pdfs=False,
        machine_filter="inactive",
        unpack_filter_enabled=True,
        unpack_extra_months=12,
        unpack_min_filter_enabled=True,
        unpack_min_months=6,
    )
    kwargs.update(overrides)
    return BulkConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# list_profile_names
# ---------------------------------------------------------------------------


def test_list_profiles_returns_default_on_first_run():
    """When no profiles exist, Default is auto-created."""
    # Force-clear any existing profiles
    s = QSettings()
    s.beginGroup("bulk/profiles")
    s.remove("")
    s.endGroup()
    s.sync()

    names = list_profile_names()
    assert names == [DEFAULT_PROFILE_NAME]

    # Call again — still only Default
    names2 = list_profile_names()
    assert names2 == [DEFAULT_PROFILE_NAME]


def test_list_profiles_includes_saved():
    save_profile(DEFAULT_PROFILE_NAME, BulkConfig())
    save_profile("TestA", _sample_config())
    save_profile("TestB", _sample_config(top_n=99))
    names = list_profile_names()
    assert "Default" in names
    assert "TestA" in names
    assert "TestB" in names
    assert names == sorted(names, key=str.lower)


# ---------------------------------------------------------------------------
# save / load roundtrip
# ---------------------------------------------------------------------------


def test_save_and_load_profile_roundtrip():
    cfg = _sample_config()
    save_profile("FullConfig", cfg)

    loaded = load_profile("FullConfig")
    assert loaded.top_n == 50
    assert loaded.out_dir == "C:\\Test\\Out"
    assert loaded.pool_size == 8
    assert loaded.blacklist == ["ABC123", "DEF456"]
    assert loaded.custom_08_name == "Adjust"
    assert loaded.custom_08_code == 2405
    assert loaded.custom_08_sub == 2
    assert loaded.custom_05_name == "Value"
    assert loaded.custom_05_code == 2731
    assert loaded.custom_05_sub == 1
    assert loaded.generate_pdfs is False
    assert loaded.machine_filter == "inactive"
    assert loaded.unpack_filter_enabled is True
    assert loaded.unpack_extra_months == 12
    assert loaded.unpack_min_filter_enabled is True
    assert loaded.unpack_min_months == 6


def test_save_and_load_with_defaults():
    """A profile saved with all defaults should load with all defaults."""
    cfg = BulkConfig()
    save_profile("Minimal", cfg)
    loaded = load_profile("Minimal")
    assert loaded.top_n == 25
    assert loaded.pool_size == 4
    assert loaded.blacklist == []
    assert loaded.custom_08_name == ""
    assert loaded.generate_pdfs is True
    assert loaded.machine_filter == "both"
    assert loaded.unpack_filter_enabled is False
    assert loaded.unpack_min_filter_enabled is False


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_profile_removes_from_list():
    save_profile("ToDelete", _sample_config())
    assert "ToDelete" in list_profile_names()
    delete_profile("ToDelete")
    assert "ToDelete" not in list_profile_names()


def test_delete_default_raises_valueerror():
    with pytest.raises(ValueError, match="cannot be deleted"):
        delete_profile(DEFAULT_PROFILE_NAME)


# ---------------------------------------------------------------------------
# BulkConfig date-filter fields
# ---------------------------------------------------------------------------


def test_bulkconfig_includes_date_filters():
    cfg = BulkConfig(
        unpack_filter_enabled=True,
        unpack_extra_months=24,
        unpack_min_filter_enabled=True,
        unpack_min_months=3,
    )
    assert cfg.unpack_filter_enabled is True
    assert cfg.unpack_extra_months == 24
    assert cfg.unpack_min_filter_enabled is True
    assert cfg.unpack_min_months == 3


def test_bulkconfig_date_filters_clamped():
    cfg = BulkConfig(unpack_extra_months=999, unpack_min_months=-5)
    assert cfg.unpack_extra_months == 120  # clamped to max 120
    assert cfg.unpack_min_months == 0      # clamped to min 0


# ---------------------------------------------------------------------------
# last profile
# ---------------------------------------------------------------------------


def test_last_profile_persisted():
    save_profile("LastTest", _sample_config())
    set_last_profile_name("LastTest")
    assert get_last_profile_name() == "LastTest"

    # Set to a profile that doesn't exist → fall back to Default
    set_last_profile_name("GhostProfile")
    assert "GhostProfile" not in list_profile_names()
    # Note: get_last_profile_name() validates against list_profile_names()
    # and falls back to Default, but only if the name is not found in the
    # list.  Since profiles are cleared between tests and GhostProfile was
    # never saved, it should fall back.
    names = list_profile_names()
    if "GhostProfile" in names:
        # Shouldn't happen, but if Default auto-creation somehow picked it up...
        delete_profile("GhostProfile")
    result = get_last_profile_name()
    assert result == DEFAULT_PROFILE_NAME
