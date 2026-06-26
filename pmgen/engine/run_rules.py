from __future__ import annotations
from collections import defaultdict
from typing import Dict, List
import logging
from pmgen.types import PmItem, PmReport, Selection
from pmgen.rules.base import Context
from pmgen.rules.generic_life import GenericLifeRule
from pmgen.rules.kit_link import KitLinkRule
from pmgen.rules.grouping import UnitGroupingRule
from pmgen.rules.qty_override import QtyOverrideRule
from pmgen.rules.ribon_expansion import RibonExpansionRule
from pmgen.rules.inventory_check import InventoryCheckRule
from pmgen.rules.RSDF_detectection import RsdfDetectionRule

PIPELINE = [
    GenericLifeRule(),      # 1. Calc Life & Due status
    KitLinkRule(),          # 2. Add Kit Codes
    UnitGroupingRule(),     # 3. Group by Unit Logic (Drum/Feed Rolls)
    RsdfDetectionRule(),    # 4. RSDF/DSDF feed-roll detection (swaps kit)
    QtyOverrideRule(),      # 5. Apply Hard Overrides
    InventoryCheckRule(),   # 6. Inventory Check 
    RibonExpansionRule(),   # 7. Resolve Part #
]

def build_context(
    report: PmReport,
    threshold: float,
    life_basis: str,
    threshold_enabled: bool = True,
    session: object | None = None,
    settings_08_bytes: bytes | None = None,
) -> Context:
    model = (report.headers or {}).get("model", "")
    counters = report.counters or {}
    items_by_canon: Dict[str, List[PmItem]] = defaultdict(list)
    
    for it in (report.items or []):
        raw_key = (getattr(it, "canon", None) or getattr(it, "descriptor", None) or "?")
        key = raw_key.strip().upper()
        items_by_canon[key].append(it)

    return Context(
        report=report,
        model=model,
        counters=counters,  # type: ignore[arg-type]
        items_by_canon=dict(items_by_canon),
        threshold=threshold,
        life_basis=life_basis,
        threshold_enabled=threshold_enabled,
        meta={
            "session": session,
            "settings_08_bytes": settings_08_bytes,
        },
    )

def run_rules(
    report,
    threshold,
    life_basis,
    threshold_enabled=True,
    session: object | None = None,
    settings_08_bytes: bytes | None = None,
) -> Selection:
    ctx = build_context(
        report,
        threshold,
        life_basis,
        threshold_enabled,
        session=session,
        settings_08_bytes=settings_08_bytes,
    )
    
    for rule in PIPELINE:
        try:
            rule.apply(ctx)
        except Exception as e:
            logging.error(f"Rule '{rule.name}' failed on model '{ctx.model}': {e}", exc_info=True)
            ctx.optional_alerts.append(f"Internal Error: Rule {rule.name} failed.")

    due = [f for f in ctx.findings.values() if f.due]
    watch = [f for f in ctx.findings.values() if not f.due and (f.life_used or 0.0) > 0.95]
        
    ctx.meta["watch"] = watch
    ctx.meta["all_items"] = list(ctx.findings.values())
    ctx.meta["optional_alerts"] = ctx.optional_alerts
    ctx.meta["mandatory_alerts"] = ctx.mandatory_alerts
    
    return Selection(
        items=due, 
        kits=ctx.kit_selection,  # type: ignore[arg-type]
        meta=ctx.meta 
    )