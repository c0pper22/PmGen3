"""Tests for the RSDF/DSDF document-feeder feed-roll detection rule."""

from __future__ import annotations

import pytest

from pmgen.engine.run_rules import PIPELINE
from pmgen.rules.RSDF_detectection import (
    DSDF_TO_RSDF_KIT,
    RsdfDetectionRule,
    detect_df_variant,
)
from pmgen.rules.base import Context
from pmgen.types import Finding, PmReport

# Known feed-roll kit codes used across the tests.
DSDF_KIT = "KIT-ROL-DSDF"
MR_KIT = "KIT-ROL-MR-4010"
RSDF_KIT = "DF-KIT-3031"


def _make_08_bytes(value: str) -> bytes:
    """Build a minimal 08 Setting Mode CSV containing code 9903 sub 0."""
    return f"CODE, SUB, DATA,\n9903, 0, {value},\n".encode("utf-8")


def _ctx(
    kit_selection: dict[str, int],
    settings_08_bytes: bytes | None = None,
    serial: str = "TEST-SN",
    findings: dict[str, Finding] | None = None,
) -> Context:
    report = PmReport(headers={"serial": serial})
    return Context(
        report=report,
        model="",
        items_by_canon={},
        threshold=0.8,
        life_basis="page",
        kit_selection=dict(kit_selection),
        findings=dict(findings or {}),
        meta={"settings_08_bytes": settings_08_bytes},
    )


# ---------------------------------------------------------------------------
# Pure classification helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("DF-38", "RSDF"),
    ("df-38", "RSDF"),          # case-insensitive
    (" DF-38 ", "RSDF"),        # whitespace trimmed
    ("DF-13", "DSDF"),
    ("DF-31", "DSDF"),
    ("N/A", "UNKNOWN"),
    ("DF-", "UNKNOWN"),
    ("DF-32", "UNKNOWN"),       # not yet categorised
    ("", "UNKNOWN"),
    (None, "UNKNOWN"),
])
def test_detect_df_variant(value, expected):
    assert detect_df_variant(value) == expected


# ---------------------------------------------------------------------------
# Rule.apply behaviour (unidirectional: only acts when RSDF is detected)
# ---------------------------------------------------------------------------

def test_rule_is_registered_in_pipeline():
    assert any(isinstance(rule, RsdfDetectionRule) for rule in PIPELINE)


def test_mapping_covers_known_dsdf_kits():
    # Guards the contract that both known DSDF feed-roll kits resolve to the
    # RSDF kit. Extend when new feeder variants are introduced.
    assert DSDF_TO_RSDF_KIT[DSDF_KIT] == RSDF_KIT
    assert DSDF_TO_RSDF_KIT[MR_KIT] == RSDF_KIT


def test_no_dsdf_kit_is_a_noop():
    # No DSDF feed-roll kit in the selection -> no fetch, no change.
    ctx = _ctx({"EPU-KIT-FC505CLR": 1}, settings_08_bytes=_make_08_bytes("DF-38"))
    RsdfDetectionRule().apply(ctx)
    assert ctx.kit_selection == {"EPU-KIT-FC505CLR": 1}
    assert ctx.optional_alerts == []


def test_rsdf_detected_swaps_dsdf_kit_to_rsdf_and_alerts():
    finding = Finding(canon="DF FEED ROLLER", due=True, kit_code=DSDF_KIT)
    ctx = _ctx(
        {DSDF_KIT: 1},
        settings_08_bytes=_make_08_bytes("DF-38"),
        findings={finding.canon: finding},
    )

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {RSDF_KIT: 1}
    assert finding.kit_code == RSDF_KIT
    assert any("RSDF Detected" in a for a in ctx.optional_alerts)


def test_rsdf_detected_swaps_mr_4010_kit_to_rsdf():
    # Some models use KIT-ROL-MR-4010 as their DSDF feed-roll kit.
    finding = Finding(canon="DF FEED ROLLER", due=True, kit_code=MR_KIT)
    ctx = _ctx(
        {MR_KIT: 1},
        settings_08_bytes=_make_08_bytes("DF-38"),
        findings={finding.canon: finding},
    )

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {RSDF_KIT: 1}
    assert finding.kit_code == RSDF_KIT
    assert any("RSDF Detected" in a for a in ctx.optional_alerts)


def test_rsdf_kit_already_selected_is_left_alone():
    # No DSDF kit to swap -> nothing happens, no alert.
    ctx = _ctx({RSDF_KIT: 1}, settings_08_bytes=_make_08_bytes("DF-38"))

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {RSDF_KIT: 1}
    assert ctx.optional_alerts == []


def test_dsdf_detected_does_not_swap():
    finding = Finding(canon="DF FEED ROLLER", due=True, kit_code=DSDF_KIT)
    ctx = _ctx(
        {DSDF_KIT: 1},
        settings_08_bytes=_make_08_bytes("DF-13"),
        findings={finding.canon: finding},
    )

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {DSDF_KIT: 1}
    assert finding.kit_code == DSDF_KIT
    assert ctx.optional_alerts == []


def test_unknown_value_does_not_swap():
    # N/A is a clean unknown: keep the DSDF kit, no alert.
    ctx = _ctx({DSDF_KIT: 1}, settings_08_bytes=_make_08_bytes("N/A"))

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {DSDF_KIT: 1}
    assert ctx.optional_alerts == []


def test_missing_08_bytes_does_not_swap_and_does_not_fetch_for_unknown_serial(monkeypatch):
    # No 08 bytes and an unknown serial -> rule must NOT hit the network and
    # must leave the DSDF kit in place (assume DSDF).
    def _boom(*args, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("get_service_file_bytes should not be called")

    monkeypatch.setattr("pmgen.io.http_client.get_service_file_bytes", _boom)

    ctx = _ctx({DSDF_KIT: 1}, settings_08_bytes=None, serial="Unknown")

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {DSDF_KIT: 1}
    assert ctx.optional_alerts == []


def test_fetch_failure_does_not_swap(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("pmgen.io.http_client.get_service_file_bytes", _raise)

    ctx = _ctx({DSDF_KIT: 1}, settings_08_bytes=None, serial="REAL-SN")

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {DSDF_KIT: 1}
    assert ctx.optional_alerts == []


def test_quantity_is_preserved_when_swapping():
    ctx = _ctx({DSDF_KIT: 3}, settings_08_bytes=_make_08_bytes("DF-38"))

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {RSDF_KIT: 3}


def test_both_dsdf_and_rsdf_selected_collapses_to_rsdf_when_rsdf_detected():
    # If both a DSDF and the RSDF kit were somehow selected, only the DSDF kit
    # is swapped; quantities roll up onto the RSDF kit.
    ctx = _ctx(
        {DSDF_KIT: 1, RSDF_KIT: 1},
        settings_08_bytes=_make_08_bytes("DF-38"),
    )

    RsdfDetectionRule().apply(ctx)

    assert ctx.kit_selection == {RSDF_KIT: 2}
