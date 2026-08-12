from __future__ import annotations
import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.platypus.flowables import KeepTogether, HRFlowable
from reportlab.platypus.doctemplate import LayoutError
try:
    import pandas as pd
    from PyQt6.QtCore import QStandardPaths
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

def _pct_color(v) -> colors.Color:
    p = v
    if p < 84.0:
        return colors.darkgray
    elif p < 100.0:
        return colors.orange
    else:
        return colors.red

def _hline(thickness=1, color=colors.HexColor("#DDDDDD")):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceBefore=4, spaceAfter=6)

def _load_inventory_map():
    """
    Loads inventory from cache and returns a dict: {(PartNumber, UnitName): Quantity}
    Note: The grouping key order here is (Part Number, Unit Name)
    """
    if not HAS_DEPS:
        return {}
    try:
        base_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        path = os.path.join(base_dir, "inventory_cache.csv")
        if not os.path.exists(path):
            return {}
        
        df = pd.read_csv(path)
        if "Part Number" in df.columns:
            df["Part Number"] = df["Part Number"].astype(str).str.strip().str.upper()
        if "Unit Name" in df.columns:
            df["Unit Name"] = df["Unit Name"].astype(str).str.strip().str.upper()
        if "Quantity" in df.columns:
            df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
                
        return df.groupby(["Part Number", "Unit Name"])["Quantity"].sum().to_dict()
    
    except Exception:
        return {}

def _make_parts_table(rows, col_names=("Qty", "Part Number", "Unit")):
    data = [list(col_names)]
    for qty, pn, unit in rows:
        data.append([str(int(qty)), pn, unit])

    tbl = Table(data, colWidths=[0.7 * inch, 3.0 * inch, 3.05 * inch], hAlign="LEFT")
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3B82F6")), 
        ("FONT", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 1), (0, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
    ]))
    for r in range(1, len(data)):
        if r % 2 == 0:
            tbl.setStyle(TableStyle([("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F8FAFC"))]))

    tbl.splitByRow = 1
    tbl.repeatRows = 1
    return tbl

def _make_inventory_check_table(rows):
    """
    Rows: [Need, Have, Order, Part, Unit, ColorCode]
    ColorCode: 0=Red, 1=Yellow, 2=Green
    """
    data = [["Needed", "Have", "Order", "Part Number", "Unit"]]
    
    # Base styles
    style_cmds = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#111827")), 
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E5E7EB")),
        ("ALIGN", (0, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9CA3AF")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
    ]
    
    for i, r in enumerate(rows):
        # r = [need, have, order, pn, unit, color_code]
        row_data = [str(r[0]), str(r[1]), str(r[2]), r[3], r[4]]
        data.append(row_data)
        
        c_code = r[5]
        if c_code == 0:
             bg = colors.HexColor("#FECACA") 
        elif c_code == 1:
             bg = colors.HexColor("#FEF3C7") 
        else:
             bg = colors.HexColor("#DCFCE7") 
             
        style_cmds.append(('BACKGROUND', (0, i+1), (-1, i+1), bg))

    tbl = Table(data, colWidths=[0.8*inch, 0.8*inch, 0.8*inch, 2.8*inch, 2.3*inch], hAlign="LEFT")
    tbl.setStyle(TableStyle(style_cmds))
    tbl.splitByRow = 1
    tbl.repeatRows = 1
    return tbl

def _make_toc_grid(toc_rows, text_style, cols=4):
    """
    Creates a compact grid TOC with lightened (alpha-adjusted) background colors.
    """
    data = []
    row_buffer = []
    cell_styles = [] 
    
    col_width = (7.0 / cols) * inch

    for index, (serial, model, score, unpack_str, machine_status) in enumerate(toc_rows):
        base_color = _pct_color(score)
        bg_color = colors.Color(base_color.red, base_color.green, base_color.blue, alpha=0.3)
        
        text_hex = "#111827"
        muted_hex = "#6B7280"
        
        extra = f'<br/><font size="7" color="{muted_hex}">Unpacked: {unpack_str}</font>' if unpack_str else ""
        serial_label = f"(*) {serial}" if str(machine_status).strip().lower() == "inactive" else serial
        link_text = (
            f'<a href="#{serial}" color="{text_hex}"><u>{serial_label}</u></a> '
            f'<font size="8" color="{text_hex}"><b>({score:.0f}%)</b></font>{extra}'
        )
        
        p = Paragraph(link_text, text_style)
        row_buffer.append(p)
        
        curr_col = len(row_buffer) - 1
        curr_row = len(data)
        cell_styles.append((curr_col, curr_row, bg_color))
        
        if len(row_buffer) == cols:
            data.append(row_buffer)
            row_buffer = []

    if row_buffer:
        while len(row_buffer) < cols:
            row_buffer.append("")
        data.append(row_buffer)

    if not data:
        return None

    tbl = Table(data, colWidths=[col_width] * cols, hAlign="LEFT")
    
    table_cmds = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
    ]
    
    for col, row, color in cell_styles:
        table_cmds.append(("BACKGROUND", (col, row), (col, row), color))
    
    tbl.setStyle(TableStyle(table_cmds))
    return tbl

def write_final_summary_pdf(
    *, out_dir: str, results: list, top: list, thr: float, basis: str,
    filename: str = "Final_Summary.pdf", threshold_enabled: bool = True
):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)

    doc = SimpleDocTemplate(path, pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.75 * inch, bottomMargin=0.75 * inch, title="Bulk Final Summary", author="PmGen")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#111827"), spaceAfter=8))
    styles.add(ParagraphStyle(name="Meta", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#374151"), spaceAfter=3))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=colors.HexColor("#111827"), spaceBefore=10, spaceAfter=6))
    styles.add(ParagraphStyle(name="Muted", parent=styles["BodyText"], fontName="Helvetica-Oblique", fontSize=9, textColor=colors.HexColor("#6B7280"), spaceAfter=6))
    
    styles.add(ParagraphStyle(
        name="SerialHeader", 
        parent=styles["BodyText"], 
        fontName="Helvetica-Bold", 
        fontSize=11, 
        leading=16,
        textColor=colors.white,
        backColor=colors.HexColor("#4B5563"),
        borderPadding=6,
        spaceBefore=12, 
        spaceAfter=8
    ))
    styles.add(ParagraphStyle(name="TOCLink", parent=styles["BodyText"], fontName="Helvetica", fontSize=10, textColor=colors.blue, alignment=1)) # 1=Center

    # --- 1. PRE-CALCULATION ---
    total_over_upn: dict[tuple[str, str], int] = {}
    total_thr_upn: dict[tuple[str, str], int] = {}
    individual_serials_story = [] 
    toc_data = []

    for r in top:
        serial = r.get("serial", "UNKNOWN")
        model = r.get("model", "UNKNOWN MODEL")
        best_used = r.get("best_used", 0.0) * 100

        customer = r.get("customer_name", "")   
        
        unpacking_date = r.get("unpacking_date")
        unpack_str = str(unpacking_date) if unpacking_date else ""
        machine_status = r.get("machine_status", "")

        toc_data.append((serial, model, best_used, unpack_str, machine_status))

        c = _pct_color(best_used)
        hexcolor = f"#{int(c.red*255):02X}{int(c.green*255):02X}{int(c.blue*255):02X}"
        
        # --- UPDATED HEADER LOGIC TO INCLUDE CUSTOMER ---
        extras = []
        if customer:
             extras.append(f"Customer: {customer}")
        if unpack_str:
             extras.append(f"Unpacked: {unpack_str}")
        
        extra_txt = " | ".join(extras)
        
        if extra_txt:
            suffix_html = f"<br/><font size='9' color='#D1D5DB'>{extra_txt}</font>"
        else:
            suffix_html = ""
        
        serial_line = f"<a name='{serial}'/>{serial} &nbsp;|&nbsp; <font color='{hexcolor}'>{best_used:.1f}%</font> &nbsp;|&nbsp; {model}{suffix_html}"
        
        individual_serials_story.append(Paragraph(serial_line, styles["SerialHeader"]))

        grouped   = r.get("grouped") or {}
        flat      = r.get("flat") or {}
        kit_by_pn = r.get("kit_by_pn") or {}
        due_src   = r.get("due_sources") or {}

        over_100_kits  = set((due_src.get("over_100") or []))
        threshold_kits = set((due_src.get("threshold") or []))
        if not threshold_enabled:
            threshold_kits = set()
        threshold_only = threshold_kits - over_100_kits

        rows_over: list = []
        rows_thr: list = []

        if grouped:
            for unit, pnmap in grouped.items():
                for pn, qty in (pnmap or {}).items():
                    unit_name = unit or "UNKNOWN-UNIT"
                    q_int = int(qty)
                    row = [q_int, pn, unit_name]
                    if unit in over_100_kits:
                        total_over_upn[(unit_name, pn)] = total_over_upn.get((unit_name, pn), 0) + q_int
                        rows_over.append(row)
                    elif unit in threshold_only:
                        total_thr_upn[(unit_name, pn)] = total_thr_upn.get((unit_name, pn), 0) + q_int
                        rows_thr.append(row)
        else:
            if not flat:
                individual_serials_story.append(Paragraph("(no final parts)", styles["Muted"]))
            else:
                for pn, qty in flat.items():
                    unit = kit_by_pn.get(pn, "UNKNOWN-UNIT")
                    q_int = int(qty)
                    row = [q_int, pn, unit]
                    if unit in over_100_kits:
                        total_over_upn[(unit, pn)] = total_over_upn.get((unit, pn), 0) + q_int
                        rows_over.append(row)
                    elif unit in threshold_only:
                        total_thr_upn[(unit, pn)] = total_thr_upn.get((unit, pn), 0) + q_int
                        rows_thr.append(row)

        individual_serials_story.append(Paragraph("Final Parts — Over 100%", styles["Section"]))
        individual_serials_story.append(_hline())
        if rows_over:
            rows_over.sort(key=lambda x: (x[2], x[1]))
            tbl_over = _make_parts_table(rows_over)
            try:
                individual_serials_story.append(KeepTogether([tbl_over]))
            except LayoutError:
                individual_serials_story.append(tbl_over)
        else:
            individual_serials_story.append(Paragraph("(none)", styles["Muted"]))
        individual_serials_story.append(Spacer(1, 0.10 * inch))

        individual_serials_story.append(Paragraph(f"Final Parts — Threshold - {thr*100:.1f}%", styles["Section"]))
        individual_serials_story.append(_hline())
        if rows_thr:
            rows_thr.sort(key=lambda x: (x[2], x[1]))
            tbl_thr = _make_parts_table(rows_thr)
            try:
                individual_serials_story.append(KeepTogether([tbl_thr]))
            except LayoutError:
                individual_serials_story.append(tbl_thr)
        else:
            individual_serials_story.append(Paragraph("(none)", styles["Muted"]))
        
        individual_serials_story.append(Spacer(1, 0.2 * inch))
        individual_serials_story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#9CA3AF"), dash=(4, 4)))
        individual_serials_story.append(Spacer(1, 0.2 * inch))

    # --- 2. BUILD THE FINAL PDF STORY ---
    story = []

    story.append(Paragraph("Bulk Final Summary", styles["H1"]))
    story.append(_hline())

    successful = len([r for r in results if r.get("ok", True)])
    thr_str = f"{thr*100:.1f}%" if threshold_enabled else "Off (only >100% due)"
    meta_lines = [
        f"Threshold: <b>{thr_str}</b> • Basis: <b>{basis.upper()}</b>",
        f"Selected top <b>{len(top)}</b> of <b>{successful}</b> successful (from <b>{len(results)}</b> attempts).",
        f"Generated: {datetime.now().strftime('%Y-%m-%d')}",
    ]
    for ml in meta_lines:
        story.append(Paragraph(ml, styles["Meta"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Quick Links", styles["Section"]))
    if toc_data:
        story.append(_make_toc_grid(toc_data, styles["TOCLink"], cols=4))
    else:
        story.append(Paragraph("(No serials generated)", styles["Muted"]))
    story.append(Spacer(1, 0.25 * inch))


    # B. INVENTORY CHECK (Combined & Factored)
    inv_map = _load_inventory_map()
    bulk_alerts = []
    combined_needed = total_over_upn.copy()
    for k, v in total_thr_upn.items():
        combined_needed[k] = combined_needed.get(k, 0) + v

    if not inv_map and combined_needed:
        bulk_alerts.append("Inventory cache is empty or missing. All items marked as order needed.")

    # [INVENTORY LOGIC KEEP PRESERVED EXACTLY AS IS, SINCE THIS IS A CRITICAL SECTION WITH COMPLEX MATCHING]
    inv_rows = []
    if combined_needed:
        for unit, needed_qty in sorted(combined_needed.items(), key=lambda k: (k[0][0], k[0][1])):
            
            found_matches = []
            pattern = r"\b" + re.escape(unit[0]) + r"\b"
            
            for inv_key, inv_qty in inv_map.items():
                if re.search(pattern, inv_key[1]):
                    found_matches.append((inv_key, inv_qty))

            if len(found_matches) > 1:
                best_matches = []
                for match in found_matches:
                    inv_name = match[0][1]
                    start_index = inv_name.find(unit[0])
                    
                    if start_index != -1:
                        remainder = inv_name[start_index + len(unit[0]):]
                        if (not remainder) or (remainder[0] == ' ') or (remainder.startswith('- ')):
                            best_matches.append(match)
                if len(best_matches) > 0:
                    found_matches = best_matches

            have_qty = 0
            if len(found_matches) == 0:
                have_qty = 0
            elif len(found_matches) == 1:
                have_qty = int(found_matches[0][1])
            else:
                conflict_names = [m[0][1] for m in found_matches[:3]]
                msg = f"Collision for '{unit[0]}': Matched {len(found_matches)} items {conflict_names}..."
                print(f"⚠️ {msg}")
                bulk_alerts.append(msg)
                have_qty = int(found_matches[0][1])

            order_qty = max(0, needed_qty - have_qty)
            if have_qty == 0:
                code = 0
            elif have_qty < needed_qty:
                code = 1
            else:
                code = 2
            
            u_name = unit[0]
            pn_key = unit[1]
            inv_rows.append([needed_qty, have_qty, order_qty, pn_key, u_name, code])
    # [END INVENTORY LOGIC]

    if bulk_alerts:
        if "AlertText" not in styles:
            styles.add(ParagraphStyle(name="AlertText", parent=styles["BodyText"], textColor=colors.red, fontSize=10, spaceAfter=2))
        
        story.append(Paragraph("⚠️ Generation Alerts", styles["Section"]))
        story.append(_hline(color=colors.red))
        for alert in bulk_alerts:
            story.append(Paragraph(f"• {alert}", styles["AlertText"]))
        story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Inventory Check — Order List", styles["Section"]))
    story.append(_hline())
    if inv_rows:
        story.append(_make_inventory_check_table(inv_rows))
    else:
        story.append(Paragraph("(no parts needed)", styles["Muted"]))
    story.append(Spacer(1, 0.3 * inch))

    # C. Consolidated parts (Original Tables)
    story.append(Paragraph("All Serials — Consolidated Parts — Over 100%", styles["Section"]))
    story.append(_hline())
    if total_over_upn:
        rows = []
        for (unit, pn), qty in sorted(total_over_upn.items(), key=lambda k: (k[0][0], k[0][1])):
            rows.append([qty, pn, unit])
        story.append(_make_parts_table(rows))
    else:
        story.append(Paragraph("(none)", styles["Muted"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph(f"All Serials — Consolidated Parts — Threshold - {thr*100:.1f}%", styles["Section"]))
    story.append(_hline())
    if total_thr_upn:
        rows = []
        for (unit, pn), qty in sorted(total_thr_upn.items(), key=lambda k: (k[0][0], k[0][1])):
            rows.append([qty, pn, unit])
        story.append(_make_parts_table(rows))
    else:
        story.append(Paragraph("(none)", styles["Muted"]))
    
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("Individual Serial Breakdowns", styles["H1"]))
    story.append(_hline())
    story.append(Spacer(1, 0.1 * inch))

    # D. Individual Serials
    story.extend(individual_serials_story)

    doc.build(story)
    return path