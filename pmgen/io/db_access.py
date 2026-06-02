import sqlite3
import string
from typing import Dict, List, Set, Tuple

from pmgen.io.http_client import get_db_path


class CatalogDB:
    """
    Helper class to manage interactions with catalog_manager.db.
    Handles Models, PM Units, Unit Contents, and Canon Mappings.
    """

    def __init__(self):
        self.db_path = get_db_path()
        self._ensure_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _ensure_tables(self):
        """Ensures required tables exist to prevent crashes on fresh installs."""
        conn = self._get_conn()
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS models (
                model_name TEXT PRIMARY KEY
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pm_units (
                unit_name TEXT PRIMARY KEY
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS model_catalog (
                model_name TEXT,
                unit_name TEXT,
                PRIMARY KEY (model_name, unit_name),
                FOREIGN KEY(model_name) REFERENCES models(model_name) ON DELETE CASCADE,
                FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS unit_items (
                unit_name TEXT,
                canon_item TEXT,
                FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS canon_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern TEXT NOT NULL,
                template TEXT NOT NULL
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qty_overrides (
                unit_name TEXT PRIMARY KEY,
                quantity INTEGER NOT NULL,
                FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name) ON DELETE CASCADE
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS per_color_units (
                unit_name TEXT PRIMARY KEY,
                FOREIGN KEY(unit_name) REFERENCES pm_units(unit_name) ON DELETE CASCADE
            )
            """
        )

        conn.commit()
        conn.close()

    # =========================================================================
    # MODELS
    # =========================================================================

    def get_all_models(self) -> List[str]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT model_name FROM models ORDER BY model_name")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def add_model(self, model_name: str):
        model_norm = (model_name or "").upper().strip()
        if not model_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO models (model_name) VALUES (?)", (model_norm,))
            conn.commit()
        finally:
            conn.close()

    def update_model(self, old_name: str, new_name: str):
        old_norm = (old_name or "").upper().strip()
        new_norm = (new_name or "").upper().strip()
        if not old_norm or not new_norm or old_norm == new_norm:
            return

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM models WHERE model_name = ?", (old_norm,))
            if not cur.fetchone():
                return
            cur.execute("SELECT 1 FROM models WHERE model_name = ?", (new_norm,))
            if cur.fetchone():
                raise ValueError(f"Model already exists: {new_norm}")

            cur.execute("UPDATE models SET model_name = ? WHERE model_name = ?", (new_norm, old_norm))
            cur.execute("UPDATE model_catalog SET model_name = ? WHERE model_name = ?", (new_norm, old_norm))
            conn.commit()
        finally:
            conn.close()

    def delete_model(self, model_name: str):
        model_norm = (model_name or "").upper().strip()
        if not model_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM model_catalog WHERE model_name = ?", (model_norm,))
            cur.execute("DELETE FROM models WHERE model_name = ?", (model_norm,))
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # PM UNITS (Kits)
    # =========================================================================

    def get_all_units(self) -> List[str]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT unit_name FROM pm_units ORDER BY unit_name")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def add_unit(self, unit_name: str):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO pm_units (unit_name) VALUES (?)", (unit_norm,))
            conn.commit()
        finally:
            conn.close()

    def update_unit(self, old_name: str, new_name: str):
        old_norm = (old_name or "").strip()
        new_norm = (new_name or "").strip()
        if not old_norm or not new_norm or old_norm == new_norm:
            return

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pm_units WHERE unit_name = ?", (old_norm,))
            if not cur.fetchone():
                return
            cur.execute("SELECT 1 FROM pm_units WHERE unit_name = ?", (new_norm,))
            if cur.fetchone():
                raise ValueError(f"PM Unit already exists: {new_norm}")

            cur.execute("UPDATE pm_units SET unit_name = ? WHERE unit_name = ?", (new_norm, old_norm))
            cur.execute("UPDATE unit_items SET unit_name = ? WHERE unit_name = ?", (new_norm, old_norm))
            cur.execute("UPDATE model_catalog SET unit_name = ? WHERE unit_name = ?", (new_norm, old_norm))
            cur.execute("UPDATE qty_overrides SET unit_name = ? WHERE unit_name = ?", (new_norm, old_norm))
            cur.execute("UPDATE per_color_units SET unit_name = ? WHERE unit_name = ?", (new_norm, old_norm))
            conn.commit()
        finally:
            conn.close()

    def delete_unit(self, unit_name: str):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM unit_items WHERE unit_name = ?", (unit_norm,))
            cur.execute("DELETE FROM model_catalog WHERE unit_name = ?", (unit_norm,))
            cur.execute("DELETE FROM pm_units WHERE unit_name = ?", (unit_norm,))
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # LINKS (Model <-> Unit)
    # =========================================================================

    def get_units_for_model(self, model_name: str) -> List[str]:
        model_norm = (model_name or "").upper().strip()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT unit_name FROM model_catalog
                WHERE model_name = ?
                ORDER BY unit_name
                """,
                (model_norm,),
            )
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def link_unit_to_model(self, model_name: str, unit_name: str):
        model_norm = (model_name or "").upper().strip()
        unit_norm = (unit_name or "").strip()
        if not model_norm or not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO model_catalog (model_name, unit_name) VALUES (?, ?)",
                (model_norm, unit_norm),
            )
            conn.commit()
        finally:
            conn.close()

    def unlink_unit_from_model(self, model_name: str, unit_name: str):
        model_norm = (model_name or "").upper().strip()
        unit_norm = (unit_name or "").strip()
        if not model_norm or not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM model_catalog WHERE model_name = ? AND unit_name = ?",
                (model_norm, unit_norm),
            )
            conn.commit()
        finally:
            conn.close()

    def replace_units_for_model(self, model_name: str, unit_names: List[str]):
        model_norm = (model_name or "").upper().strip()
        if not model_norm:
            return
        unit_values = sorted({(unit or "").strip() for unit in unit_names if (unit or "").strip()})

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM models WHERE model_name = ?", (model_norm,))
            if not cur.fetchone():
                raise ValueError(f"Unknown model: {model_norm}")

            cur.execute("DELETE FROM model_catalog WHERE model_name = ?", (model_norm,))
            for unit_name in unit_values:
                cur.execute("SELECT 1 FROM pm_units WHERE unit_name = ?", (unit_name,))
                if cur.fetchone():
                    cur.execute(
                        "INSERT OR IGNORE INTO model_catalog (model_name, unit_name) VALUES (?, ?)",
                        (model_norm, unit_name),
                    )
            conn.commit()
        finally:
            conn.close()

    def get_model_catalog_rows(self) -> List[Tuple[str, str]]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT model_name, unit_name FROM model_catalog ORDER BY model_name, unit_name")
            return [(row[0], row[1]) for row in cur.fetchall()]
        finally:
            conn.close()

    # =========================================================================
    # UNIT CONTENTS (Items inside a Unit)
    # =========================================================================

    def get_items_for_unit(self, unit_name: str) -> List[str]:
        unit_norm = (unit_name or "").strip()
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT canon_item FROM unit_items WHERE unit_name = ? ORDER BY canon_item", (unit_norm,))
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def add_item_to_unit(self, unit_name: str, item: str):
        unit_norm = (unit_name or "").strip()
        item_norm = (item or "").strip()
        if not unit_norm or not item_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO unit_items (unit_name, canon_item) VALUES (?, ?)", (unit_norm, item_norm))
            conn.commit()
        finally:
            conn.close()

    def remove_item_from_unit(self, unit_name: str, item: str):
        unit_norm = (unit_name or "").strip()
        item_norm = (item or "").strip()
        if not unit_norm or not item_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                DELETE FROM unit_items
                WHERE rowid IN (
                    SELECT rowid FROM unit_items
                    WHERE unit_name = ? AND canon_item = ?
                    LIMIT 1
                )
                """,
                (unit_norm, item_norm),
            )
            conn.commit()
        finally:
            conn.close()

    def replace_items_for_unit(self, unit_name: str, items: List[str]):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        cleaned_items = sorted({(item or "").strip() for item in items if (item or "").strip()})

        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pm_units WHERE unit_name = ?", (unit_norm,))
            if not cur.fetchone():
                raise ValueError(f"Unknown PM Unit: {unit_norm}")

            cur.execute("DELETE FROM unit_items WHERE unit_name = ?", (unit_norm,))
            for item in cleaned_items:
                cur.execute("INSERT INTO unit_items (unit_name, canon_item) VALUES (?, ?)", (unit_norm, item))
            conn.commit()
        finally:
            conn.close()

    def get_unit_item_rows(self) -> List[Tuple[str, str]]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT unit_name, canon_item FROM unit_items ORDER BY unit_name, canon_item")
            return [(row[0], row[1]) for row in cur.fetchall()]
        finally:
            conn.close()

    # =========================================================================
    # CANON MAPPINGS (Regex)
    # =========================================================================

    _CHANNEL_VALUES = ("K", "C", "M", "Y")

    def get_mappings(self) -> List[Tuple[int, str, str]]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT id, pattern, template FROM canon_mappings ORDER BY pattern, id")
            except sqlite3.OperationalError:
                cur.execute("SELECT rowid, pattern, template FROM canon_mappings ORDER BY pattern, rowid")
            return cur.fetchall()
        finally:
            conn.close()

    @classmethod
    def _expand_canon_template(cls, template: str) -> Set[str]:
        template_norm = (template or "").strip()
        if not template_norm:
            return set()

        try:
            fields = {
                field_name.split("!", 1)[0].split(":", 1)[0]
                for _literal, field_name, _format_spec, _conversion in string.Formatter().parse(template_norm)
                if field_name
            }
        except ValueError:
            return {template_norm}

        if not fields:
            return {template_norm}

        if fields == {"chan"}:
            expanded: Set[str] = set()
            for channel in cls._CHANNEL_VALUES:
                try:
                    expanded.add(template_norm.format(chan=channel))
                except (KeyError, ValueError):
                    return {template_norm}
            return expanded

        return {template_norm}

    def get_available_canon_items(self) -> List[str]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT template FROM canon_mappings
                WHERE TRIM(COALESCE(template, '')) <> ''
                ORDER BY template COLLATE NOCASE, template
                """
            )
            items: Set[str] = set()
            for (template,) in cur.fetchall():
                items.update(self._expand_canon_template(template))
            return sorted(items, key=lambda value: (value.upper(), value))
        finally:
            conn.close()

    def add_mapping(self, pattern: str, template: str):
        pattern_norm = (pattern or "").strip()
        template_norm = (template or "").strip()
        if not pattern_norm or not template_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO canon_mappings (pattern, template) VALUES (?, ?)", (pattern_norm, template_norm))
            conn.commit()
        finally:
            conn.close()

    def delete_mapping(self, mapping_id: int):
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM canon_mappings WHERE id = ?", (mapping_id,))
            except sqlite3.OperationalError:
                cur.execute("DELETE FROM canon_mappings WHERE rowid = ?", (mapping_id,))
            conn.commit()
        finally:
            conn.close()

    def update_mapping(self, mapping_id: int, pattern: str, template: str):
        pattern_norm = (pattern or "").strip()
        template_norm = (template or "").strip()
        if not pattern_norm or not template_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "UPDATE canon_mappings SET pattern=?, template=? WHERE id=?",
                    (pattern_norm, template_norm, mapping_id),
                )
            except sqlite3.OperationalError:
                cur.execute(
                    "UPDATE canon_mappings SET pattern=?, template=? WHERE rowid=?",
                    (pattern_norm, template_norm, mapping_id),
                )
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # QTY OVERRIDES
    # =========================================================================

    def get_qty_overrides(self) -> Dict[str, int]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT unit_name, quantity FROM qty_overrides")
            return {row[0]: int(row[1]) for row in cur.fetchall()}
        finally:
            conn.close()

    def set_qty_override(self, unit_name: str, quantity: int):
        unit_norm = (unit_name or "").strip()
        if not unit_norm or quantity is None:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO qty_overrides (unit_name, quantity)
                VALUES (?, ?)
                ON CONFLICT(unit_name) DO UPDATE SET quantity = excluded.quantity
                """,
                (unit_norm, int(quantity)),
            )
            conn.commit()
        finally:
            conn.close()

    def delete_qty_override(self, unit_name: str):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM qty_overrides WHERE unit_name = ?", (unit_norm,))
            conn.commit()
        finally:
            conn.close()

    # =========================================================================
    # UNIT SEMANTICS (Per-color kit flags)
    # =========================================================================

    def get_per_color_units(self) -> List[str]:
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT unit_name FROM per_color_units ORDER BY unit_name")
            return [row[0] for row in cur.fetchall()]
        finally:
            conn.close()

    def add_per_color_unit(self, unit_name: str):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("INSERT OR IGNORE INTO per_color_units (unit_name) VALUES (?)", (unit_norm,))
            conn.commit()
        finally:
            conn.close()

    def remove_per_color_unit(self, unit_name: str):
        unit_norm = (unit_name or "").strip()
        if not unit_norm:
            return
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM per_color_units WHERE unit_name = ?", (unit_norm,))
            conn.commit()
        finally:
            conn.close()
