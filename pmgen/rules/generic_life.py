from __future__ import annotations

from typing import Optional

from pmgen.rules.base import Context, RuleBase
from pmgen.types import Finding, PmItem


def _life_used(item: PmItem, basis: str) -> Optional[float]:
    """
    Compute life_used as a fraction 0..n based on the selected basis.

    If basis == "page", prefer page_life but fall back to drive_life.
    If basis == "drive", prefer drive_life but fall back to page_life.
    Any non-numeric value is treated as missing.
    """
    p = item.page_life
    d = item.drive_life

    if basis == "page":
        return p if isinstance(p, (int, float)) else (d if isinstance(d, (int, float)) else None)
    if basis == "drive":
        return d if isinstance(d, (int, float)) else (p if isinstance(p, (int, float)) else None)

    # Fallback: try page then drive
    return p if isinstance(p, (int, float)) else (d if isinstance(d, (int, float)) else None)


def _is_due(used: Optional[float], ctx: Context) -> bool:
    """
    Central due logic:

      * Always due if life_used > 1.0 (over 100%).
      * Optionally early-due when ctx.threshold_enabled and life_used >= ctx.threshold (0–1).
    """
    if used is None:
        return False

    # Hard rule: over 100% life is always due
    if used > 1.0:
        return True

    # Optional early-due threshold (0–100%)
    if getattr(ctx, "threshold_enabled", True):
        thr = max(0.0, min(getattr(ctx, "threshold", 0.0), 1.0))
        return used >= thr

    return False


class GenericLifeRule(RuleBase):
    name = "GenericLifeRule"

    def apply(self, ctx: Context) -> None:
        for canon, items in ctx.items_by_canon.items():
            best_item = None
            best_used = -1.0
            
            for it in items:
                used = _life_used(it, ctx.life_basis)
                if used is not None and used > best_used:
                    best_used = used
                    best_item = it
            
            if best_item is None:
                continue

            is_due = _is_due(best_used, ctx)

            f = Finding(
                canon=canon,
                life_used=best_used,
                due=is_due
            )
            
            ctx.findings[canon] = f