"""Regression tests for the catalog's DF feed-roll default.

Ensures the DF feed rolls default to a DSDF kit (``KIT-ROL-DSDF`` /
``KIT-ROL-MR-4010``) and never to the RSDF kit ``DF-KIT-3031``, which must stay
canon-free. Guards against the regression where ``DF-KIT-3031`` carried the DF
feed-roll canons and won ``KitLinkRule``'s alphabetical selection for every
model, making feed rolls wrongly default to the RSDF kit.
"""

from __future__ import annotations

import sqlite3

import create_database
from pmgen.rules.RSDF_detectection import DSDF_TO_RSDF_KIT

DF_CANONS = {"DF FEED ROLLER", "DF PICK UP ROLLER", "DF SEP ROLLER"}
RSDF_KIT = "DF-KIT-3031"


def _build_catalog(tmp_path, monkeypatch) -> str:
    db = str(tmp_path / "catalog_manager.db")
    monkeypatch.setattr(create_database, "DB_PATH", db)
    create_database.migrate_data()
    return db


def _feed_roll_kit(cur, model: str) -> str | None:
    cur.execute(
        "SELECT unit_name FROM model_catalog WHERE model_name=? ORDER BY unit_name",
        (model,),
    )
    mapping: dict[str, str] = {}
    for (unit,) in cur.fetchall():
        cur.execute("SELECT canon_item FROM unit_items WHERE unit_name=?", (unit,))
        for (item,) in cur.fetchall():
            key = (item or "").strip().upper()
            if key in DF_CANONS:
                mapping.setdefault(key, unit)
    return mapping.get("DF FEED ROLLER")


def test_df_kit_3031_is_canon_free(tmp_path, monkeypatch):
    db = _build_catalog(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT canon_item FROM unit_items WHERE unit_name=?", (RSDF_KIT,))
        assert [r[0] for r in cur.fetchall()] == []
    finally:
        conn.close()


def test_feed_rolls_never_default_to_rsdf_kit(tmp_path, monkeypatch):
    db = _build_catalog(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT model_name FROM models ORDER BY model_name")
        bad = []
        for (model,) in cur.fetchall():
            kit = _feed_roll_kit(cur, model)
            if kit is None:
                continue  # model has no DF feed rolls
            if kit == RSDF_KIT:
                bad.append(model)
        assert bad == [], f"models defaulting feed rolls to RSDF kit: {bad}"
    finally:
        conn.close()


def test_rsdf_models_default_to_a_known_dsdf_kit(tmp_path, monkeypatch):
    """Models whose DSDF kit is in the RSDF mapping must actually default to it."""
    db = _build_catalog(tmp_path, monkeypatch)
    conn = sqlite3.connect(db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT model_name FROM models ORDER BY model_name")
        for (model,) in cur.fetchall():
            kit = _feed_roll_kit(cur, model)
            if kit is None:
                continue
            # If a model defaults to a DSDF kit we swap from, it must be one we
            # know how to upgrade to RSDF. (Older platforms like 330AC/400AC use
            # their own DF kit and are intentionally outside the swap.)
            if kit in DSDF_TO_RSDF_KIT:
                assert DSDF_TO_RSDF_KIT[kit] == RSDF_KIT
    finally:
        conn.close()
