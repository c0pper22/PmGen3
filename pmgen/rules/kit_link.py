from __future__ import annotations
from typing import Dict, Iterable
from pmgen.rules.base import Context, RuleBase
from pmgen.io.db_access import CatalogDB


def _canon_to_kit_map_from_db(model: str) -> Dict[str, str]:
    """
    Build {canon -> kit_code} directly from SQLite for the best model match.
    """
    mapping: Dict[str, str] = {}
    if not model:
        return mapping

    try:
        db = CatalogDB()
        up = model.upper()
        db_models = db.get_all_models()

        candidates = [m for m in db_models if m and m in up]
        if not candidates:
            return mapping

        # Prefer the most specific model token if multiple are present.
        matched_model = sorted(candidates, key=lambda m: (-len(m), m))[0]

        for unit_name in db.get_units_for_model(matched_model):
            canons: Iterable[str] = db.get_items_for_unit(unit_name)
            for canon in canons:
                key = (canon or "").strip().upper()
                if key:
                    mapping.setdefault(key, unit_name)
    except Exception:
        return {}

    return mapping

class KitLinkRule(RuleBase):
    name = "KitLinkRule"
    _CACHE: Dict[str, Dict[str, str]] = {}

    @classmethod
    def clear_cache(cls):
        cls._CACHE.clear()

    def _get_cached_map(self, model: str) -> Dict[str, str]:
        cache_key = (model or "").upper()
        if cache_key in self._CACHE:
            return self._CACHE[cache_key]

        cmap = _canon_to_kit_map_from_db(model)
        self._CACHE[cache_key] = cmap
        return cmap

    def apply(self, ctx: Context) -> None:
        model = ctx.model
        cmap = self._get_cached_map(model)
        if not cmap:
            ctx.optional_alerts.append(f"Could not link part to kit, No parts catalog found for model '{model}'.")
            return

        for canon, finding in ctx.findings.items():
            if not finding.due:
                continue

            kit_code = cmap.get((canon or "").strip().upper())
            if kit_code:
                setattr(finding, "kit_code", kit_code)
            else:
                ctx.optional_alerts.append(f"Missing Link: Item '{canon}' is DUE, but no Kit Code is defined in catalog.")