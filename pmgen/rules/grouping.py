from pmgen.rules.base import RuleBase, Context
import re
from typing import Dict, Optional, Tuple, Set
from pmgen.io.db_access import CatalogDB 

# ---------------------------
# Helpers for unit semantics
# ---------------------------
def _canon_channel(canon: Optional[str]) -> Optional[str]:
    """Return 'K'/'C'/'M'/'Y' if the canon includes a color channel, else None."""
    if not canon:
        return None
    m = re.search(r"\[(K|C|M|Y)\]", canon.upper())
    return m.group(1) if m else None

def _is_drum_canon(canon: Optional[str]) -> bool:
    """Identify canons that should be counted *per color drum* only."""
    if not canon:
        return False
    u = canon.upper().strip()
    return u.startswith("DRUM[") and u.endswith("]") and "BLADE" not in u

def _is_cst_canon(canon: Optional[str]) -> bool:
    """Return True if the canon belongs to a paper cassette (CST) unit."""
    if not canon:
        return False
    u = canon.upper()
    return "CST" in u

def _cassette_slot_id(canon: Optional[str]) -> Optional[str]:
    """Extract a per-tray id: 1st/2nd/3rd/4th CST (uppercased), else None."""
    if not canon:
        return None
    m = re.search(r"\((?P<slot>(1ST|2ND|3RD|4TH)\s*CST\.?)\)", canon.upper())
    return m.group("slot") if m else None

def _unit_bucket_key(
    kit_code: str,
    canon: Optional[str],
    per_color_units: Set[str],
) -> Tuple[str, Optional[str]]:
    """
    Build the *unit* key used to ensure we count each PmUnit once.
    - Normal units:              (kit_code, None)
    - Per-color kits (declared): (kit_code, <channel>)           → once per K/C/M/Y
    - Drum units:                (kit_code, canon)               → per color (DRUM[K/C/M/Y])
    - CST units:                 (kit_code, <tray-slot>)         → per tray (1st/2nd/3rd/4th)
    """
    # 1) Explicit per-color kits (e.g., EPU-KIT-FC556-G)
    if kit_code in per_color_units:
        ch = _canon_channel(canon)
        return (kit_code, ch or "<per-color>")

    # 2) Drums are per-color by canon name
    if _is_drum_canon(canon):
        return (kit_code, canon or "<per-canon>")

    # 3) Paper cassettes are per-tray
    if _is_cst_canon(canon):
        slot = _cassette_slot_id(canon)
        return (kit_code, slot or "<cst>")

    # 4) Everything else counts once
    return (kit_code, None)

class UnitGroupingRule(RuleBase):
    """
    Responsible for converting a list of Due Findings into a list of Unit Quantities.
    Handles 'Drum per color', 'CST per tray', etc.
    """
    name = "UnitGroupingRule"
    _PER_COLOR_CACHE: Optional[Set[str]] = None

    @classmethod
    def clear_cache(cls):
        cls._PER_COLOR_CACHE = None

    def _get_per_color_units(self) -> Set[str]:
        if self._PER_COLOR_CACHE is not None:
            return self._PER_COLOR_CACHE
        try:
            units = CatalogDB().get_per_color_units()
            self._PER_COLOR_CACHE = set(units)
        except Exception:
            self._PER_COLOR_CACHE = set()
        return self._PER_COLOR_CACHE

    def apply(self, ctx: Context) -> None:
        seen_buckets = set()
        selection = {}
        per_color_units = self._get_per_color_units()

        for finding in ctx.findings.values():
            if not finding.due or not getattr(finding, "kit_code", None):
                continue

            kit = finding.kit_code
            canon = finding.canon

            # Use your helper logic here (moved from run_rules.py)
            bucket_key = self._get_bucket_key(kit, canon, per_color_units)

            if bucket_key in seen_buckets:
                continue

            seen_buckets.add(bucket_key)
            selection[kit] = selection.get(kit, 0) + 1

        # Deduplication removes sub-kits if a super-kit covering them is already selected
        self._apply_db_deduplication(selection)

        ctx.kit_selection = selection

    def _get_bucket_key(self, kit, canon, per_color_units):
        return _unit_bucket_key(kit_code=kit, canon=canon, per_color_units=per_color_units)

    def _apply_db_deduplication(self, selection: Dict[str, int]):
        """
        Uses the SQLite DB (unit_items) to detect if one selected kit
        is a subset of another selected kit, reducing redundancy.
        """
        # 1. Identify active kits
        kits = [k for k, v in selection.items() if v > 0]
        if not kits:
            return

        try:
            db = CatalogDB()
            
            # 2. Fetch contents for all selected kits from SQLite
            contents: Dict[str, Set[str]] = {}
            for k in kits:
                items = db.get_items_for_unit(k)
                if items:
                    contents[k] = set(items)

            # 3. Sort by size descending (Largest kits eat smallest kits)
            #    If sizes are equal, order is stable/arbitrary, which is fine for duplicates.
            sorted_kits = sorted(kits, key=lambda k: len(contents.get(k, set())), reverse=True)

            # 4. Compare pairs
            for i, super_k in enumerate(sorted_kits):
                if super_k not in contents:
                    continue

                super_qty = selection.get(super_k, 0)
                if super_qty <= 0:
                    continue

                super_items = contents[super_k]

                # Check against all subsequent (smaller/equal) kits
                for sub_k in sorted_kits[i + 1:]:
                    if sub_k not in contents:
                        continue

                    sub_qty = selection.get(sub_k, 0)
                    if sub_qty <= 0:
                        continue
                    
                    sub_items = contents[sub_k]
                    
                    # If sub_kit is fully contained in super_kit
                    if sub_items and sub_items.issubset(super_items):
                        # We have the Super kit, so we don't need the Sub kit 
                        # (up to the quantity of the Super kit).
                        deduct = min(super_qty, sub_qty)
                        selection[sub_k] -= deduct

            # 5. Clean up zeroed entries
            for k in list(selection.keys()):
                if selection[k] <= 0:
                    del selection[k]

        except Exception as e:
            print(f"[UnitGroupingRule] Deduplication warning: {e}")