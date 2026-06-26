from __future__ import annotations
from typing import Dict, Optional
from pmgen.rules.base import Context, RuleBase
from pmgen.io.db_access import CatalogDB

class QtyOverrideRule(RuleBase):
    name = "QtyOverrideRule"

    # Class-level cache so clear_cache() can invalidate it for every instance,
    # including the singleton held by the rules PIPELINE. Overrides are loaded
    # lazily on first apply() instead of in __init__ so catalog edits take
    # effect after clear_cache() without restarting the app.
    _OVERRIDES_CACHE: Optional[Dict[str, int]] = None

    @classmethod
    def clear_cache(cls) -> None:
        """Clear cached quantity overrides so the next apply() reloads from the catalog DB."""
        cls._OVERRIDES_CACHE = None

    def _get_overrides(self) -> Dict[str, int]:
        if QtyOverrideRule._OVERRIDES_CACHE is None:
            try:
                QtyOverrideRule._OVERRIDES_CACHE = CatalogDB().get_qty_overrides()
            except Exception:
                QtyOverrideRule._OVERRIDES_CACHE = {}
        return QtyOverrideRule._OVERRIDES_CACHE

    def apply(self, ctx: Context) -> None:
        overrides = self._get_overrides()
        for kit in list(ctx.kit_selection.keys()):
            if kit in overrides:
                ctx.kit_selection[kit] = overrides[kit]