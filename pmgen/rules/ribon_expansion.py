from __future__ import annotations
from typing import Dict, Set
from pmgen.rules.base import Context, RuleBase

class RibonExpansionRule(RuleBase):
    name = "RibonExpansionRule"

    def apply(self, ctx: Context) -> None:
        from pmgen.engine.resolve_to_pn import resolve_with_rows
        # 1. Categorize Kits by "Due Reason" (Over 100% vs Threshold)
        over_100_kits: Set[str] = set()
        threshold_kits: Set[str] = set()

        for finding in ctx.findings.values():
            if not finding.due or not finding.kit_code:
                continue
            
            used = finding.life_used or 0.0
            
            if used > 1.0:
                over_100_kits.add(finding.kit_code)
            else:
                threshold_kits.add(finding.kit_code)

        ctx.meta["due_sources"] = {
            "over_100": list(over_100_kits),
            "threshold": list(threshold_kits)
        }

        # 2. Resolve to Part Numbers (Database Lookup)
        selection = ctx.kit_selection
        if not selection:
            return

        try:
            rows, flat_pns = resolve_with_rows(selection)

            for kit_code in selection.keys():
                if kit_code not in rows:
                    ctx.alerts.append(f"Database Error: Kit '{kit_code}' not found in Ribon DB (No Part #).")
            
            grouped: Dict[str, Dict[str, int]] = {}
            kit_by_pn: Dict[str, str] = {}

            for kit_code, qty_needed in selection.items():
                row_data = rows.get(kit_code)
                
                if not row_data: 
                    continue
                
                kit_rows = [row_data]

                for row in kit_rows:
                    pn = row.get("PARTS_NO")
                    if not pn:
                        continue
                        
                    q_per_kit = int(row.get("Q'TY", 1) or 1)
                    total_q = q_per_kit * qty_needed
                    
                    if kit_code not in grouped:
                        grouped[kit_code] = {}
                    
                    grouped[kit_code][pn] = grouped[kit_code].get(pn, 0) + total_q
                    
                    kit_by_pn[pn] = kit_code

            ctx.meta["selection_pn"] = flat_pns
            ctx.meta["selection_pn_grouped"] = grouped
            ctx.meta["kit_by_pn"] = kit_by_pn

        except Exception as e:
            print(f"[RibonExpansionRule] Failed to resolve parts: {e}")
            ctx.meta["error"] = str(e)