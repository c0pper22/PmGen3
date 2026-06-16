from __future__ import annotations
from pmgen.rules.base import Context, RuleBase

class InventoryCheckRule(RuleBase):
    """
    Checks the local Inventory Cache.
    Separates requirements into 'matches' (have stock) and 'missing' (need to order).
    """
    name = "InventoryCheckRule"

    def apply(self, ctx: Context) -> None:
        from pmgen.ui.inventory import load_inventory_cache
        
        # 1. Load data
        df = load_inventory_cache()
        
        # If inventory is empty/missing, EVERYTHING is missing
        if df.empty:
            missing = []
            for item_code, qty_needed in ctx.kit_selection.items():
                missing.append({
                    "code": item_code,
                    "needed": qty_needed,
                    "ordering": qty_needed
                })
            ctx.meta["inventory_missing"] = missing
            ctx.optional_alerts.append("Inventory cache is empty or missing. All items marked as order needed.")
            return

        matches = []
        missing = []

        # 2. Iterate through current selection
        for item_code, qty_needed in ctx.kit_selection.items():
            
            key = item_code.strip().upper()
            
            # 3. Look up in Inventory (Exact or Contains)
            match = df[ 
                (df['Part Number'] == key) | 
                (df['Unit Name'].str.contains(key, case=False, regex=False, na=False)) 
            ]

            qty_on_hand = 0.0
            matched_name = None

            if not match.empty:
                qty_on_hand = float(match.iloc[0]['Quantity'])
                matched_name = str(match.iloc[0]['Unit Name'])

            # 4. Compare Needed vs On Hand
            if qty_on_hand >= qty_needed:
                # Fully In Stock
                matches.append({
                    "code": item_code,
                    "matched_with": matched_name,
                    "needed": qty_needed,
                    "in_stock": qty_on_hand,
                    "covered": qty_needed
                })
            elif qty_on_hand > 0:
                # Partial Stock (Have some, need more)
                matches.append({
                    "code": item_code,
                    "matched_with": matched_name,
                    "needed": qty_needed,
                    "in_stock": qty_on_hand,
                    "covered": qty_on_hand
                })
                missing.append({
                    "code": item_code,
                    "needed": qty_needed,
                    "ordering": int(qty_needed - qty_on_hand),
                    "note": "(Partial)"
                })
            else:
                # Not in Stock at all
                missing.append({
                    "code": item_code,
                    "needed": qty_needed,
                    "ordering": qty_needed
                })

        # 5. Save to meta
        if matches:
            ctx.meta["inventory_matches"] = matches
        if missing:
            ctx.meta["inventory_missing"] = missing