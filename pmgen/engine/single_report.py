from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, List, Optional, Union

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.flowables import HRFlowable, KeepTogether

from pmgen.engine.run_rules import run_rules
from pmgen.parsing.parse_pm_report import parse_pm_report
from pmgen.types import FinalPartEntry, Finding, PmReport, SingleReportData


SEPARATOR_LINE = "─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────"


def _safe_get(mapping, key, default=None):
    try:
        return mapping.get(key, default)
    except Exception:
        return default


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{(float(value) * 100):.1f}%"
    except Exception:
        return "—"


def _report_header_fields(report) -> tuple[str, str, str]:
    headers = getattr(report, "headers", {}) or {}
    model = headers.get("model", "Unknown")
    serial = headers.get("serial", "Unknown")
    date_raw = headers.get("date")
    date_text = date_raw if isinstance(date_raw, str) and date_raw.strip() else datetime.now().strftime("%m-%d-%Y")
    return model, serial, date_text


def _build_header_line(model: str, serial: str, dt_str: str, unpacking_date: Optional[Union[str, date]]) -> str:
    header_info = f"Model: {model}  |  Serial: {serial}  |  Last Reported: {dt_str}"
    if unpacking_date:
        header_info += f" | Unpacking Date: {unpacking_date}"
    return header_info


def _append_separator_line(lines: List[str]) -> None:
    lines.append(SEPARATOR_LINE)


def _collect_all_findings(selection, show_all: bool):
    due = list(getattr(selection, "items", []) or [])
    if not show_all:
        return due

    meta = getattr(selection, "meta", {}) or {}
    pools = [
        getattr(selection, "not_due", None),
        getattr(selection, "all_items", None),
        meta.get("all"),
        meta.get("all_items"),
        meta.get("watch"),
    ]

    extra = []
    for pool in pools:
        if pool:
            extra.extend(pool)

    def _key(finding):
        return (getattr(finding, "canon", None), getattr(finding, "kit_code", None))

    seen = {_key(finding) for finding in due}
    out = list(due)
    for finding in extra:
        key = _key(finding)
        if key not in seen:
            out.append(finding)
            seen.add(key)

    out.sort(key=lambda x: (getattr(x, "life_used", None) or 0.0), reverse=True)
    return out


def _combined_findings_for_text(selection, show_all: bool):
    due_items = list(getattr(selection, "items", []) or [])
    return _collect_all_findings(selection, show_all=True) if show_all else due_items


def _combined_findings_for_pdf(selection, show_all: bool):
    due_items = list(getattr(selection, "items", []) or [])
    not_due_items = []

    if show_all:
        if hasattr(selection, "not_due") and selection.not_due:
            not_due_items = list(selection.not_due)
        else:
            meta = getattr(selection, "meta", {}) or {}
            all_items = meta.get("all_items", []) or []
            not_due_items = [finding for finding in all_items if not getattr(finding, "due", False)]

    combined = due_items + not_due_items if show_all else due_items
    combined.sort(key=lambda x: (getattr(x, "life_used", None) or 0.0), reverse=True)
    return combined


def _calc_unpack_alert(unpacking_date: Optional[Union[str, date]]) -> Optional[str]:
    """Check whether the unpacking date is older than the configured month filter."""
    older_than_filter = 48

    if not unpacking_date:
        return None

    try:
        if isinstance(unpacking_date, str):
            unpack_date = datetime.strptime(unpacking_date, "%Y-%m-%d").date()
        elif isinstance(unpacking_date, datetime):
            unpack_date = unpacking_date.date()
        else:
            unpack_date = unpacking_date

        today = date.today()
        age_months = (today.year - unpack_date.year) * 12 + (today.month - unpack_date.month)

        if age_months > older_than_filter:
            return f"Unpacking Date Alert: Unit is {age_months} months old. Talk to FSM."
    except Exception:
        pass

    return None


def _collect_mandatory_alerts(unpacking_date: Optional[Union[str, date]]) -> List[str]:
    """Collect alerts that always appear and cannot be turned off."""
    alerts: List[str] = []
    unpack_alert = _calc_unpack_alert(unpacking_date)
    if unpack_alert:
        alerts.append(unpack_alert)
    return alerts


def _collect_optional_alerts(meta: dict) -> List[str]:
    """Collect rule-generated alerts that can be toggled off in settings."""
    return list(meta.get("optional_alerts", []) or [])


def _build_counter_lines(counters: dict) -> List[str]:
    lines: List[str] = []
    if isinstance(counters, dict):
        parts = []
        if _safe_get(counters, "color") is not None:
            parts.append(f"Color: {_safe_get(counters, 'color')}")
        if _safe_get(counters, "black") is not None:
            parts.append(f"Black: {_safe_get(counters, 'black')}")
        if _safe_get(counters, "df") is not None:
            parts.append(f"DF: {_safe_get(counters, 'df')}")
        if _safe_get(counters, "total") is not None:
            parts.append(f"Total: {_safe_get(counters, 'total')}")
        if parts:
            lines.append("Counters:")
            lines.append("  " + "  ".join(parts))
    return lines


def _build_pdf_counter_parts(counters: dict) -> List[str]:
    return [f"{key.title()}: {value}" for key, value in counters.items() if value is not None]


def _build_final_parts_lists(meta: dict, threshold_enabled: bool) -> tuple[List[List[Any]], List[List[Any]]]:
    grouped = meta.get("selection_pn_grouped", {}) or {}
    flat = meta.get("selection_pn", {}) or {}
    by_pn = meta.get("kit_by_pn", {}) or {}
    due_src = meta.get("due_sources", {}) or {}

    over_100_kits = set(due_src.get("over_100", []) or [])
    threshold_kits = set(due_src.get("threshold", []) or [])
    if not threshold_enabled:
        threshold_kits = set()

    threshold_only = threshold_kits - over_100_kits

    final_over: List[List[Any]] = []
    final_thr: List[List[Any]] = []

    if grouped:
        for unit, pns in grouped.items():
            if unit in over_100_kits:
                for pn, qty in (pns or {}).items():
                    final_over.append([int(qty), pn, unit])
            elif unit in threshold_only:
                for pn, qty in (pns or {}).items():
                    final_thr.append([int(qty), pn, unit])
    elif flat:
        for pn, qty in flat.items():
            unit = by_pn.get(pn, "UNKNOWN-UNIT")
            if unit in over_100_kits:
                final_over.append([int(qty), pn, unit])
            elif unit in threshold_only:
                final_thr.append([int(qty), pn, unit])

    return final_over, final_thr


def _extract_model_code(model: str) -> str:
    found_matches = re.findall(r"\d{3,4}AC?", model)
    if found_matches:
        return found_matches[0]
    return "UnknownModel"


def _build_pdf_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="MandatoryAlertHeader", parent=styles["Heading4"], textColor=colors.red, spaceBefore=6, spaceAfter=2))
    styles.add(ParagraphStyle(name="MandatoryAlertText", parent=styles["BodyText"], textColor=colors.red, fontSize=9))
    styles.add(ParagraphStyle(name="AlertHeader", parent=styles["Heading4"], textColor=colors.orange, spaceBefore=6, spaceAfter=2))
    styles.add(ParagraphStyle(name="AlertText", parent=styles["BodyText"], textColor=colors.orange, fontSize=9))
    styles.add(ParagraphStyle(name="H1", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=colors.HexColor("#111827"), spaceBefore=0, spaceAfter=2))
    styles.add(ParagraphStyle(name="Meta", fontName="Helvetica", fontSize=9, leading=10, textColor=colors.HexColor("#374151"), spaceBefore=0, spaceAfter=2))
    styles.add(ParagraphStyle(name="Section", fontName="Helvetica-Bold", fontSize=11, leading=12, textColor=colors.HexColor("#111827"), spaceBefore=4, spaceAfter=2))
    return styles


def _pct_color(value) -> colors.Color:
    if value < 84.0:
        return colors.darkgray
    if value < 100.0:
        return colors.orange
    return colors.red


def _hline(thickness=1, color=colors.HexColor("#DDDDDD")):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceBefore=2, spaceAfter=2)


def _tbl_style_base():
    return TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#3B82F6")),
        ("FONT", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ])


def _zebra(tbl, rows):
    for row_idx in range(1, rows):
        if row_idx % 2 == 0:
            tbl.setStyle(TableStyle([("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#F8FAFC"))]))


def _configure_table(table: Table, row_count: int, extra_styles: Optional[List[tuple]] = None) -> None:
    table.setStyle(_tbl_style_base())
    if extra_styles:
        table.setStyle(TableStyle(extra_styles))
    _zebra(table, row_count)
    table.splitByRow = 1
    table.repeatRows = 1


def format_report(
    *,
    report,
    selection,
    threshold: float,
    life_basis: str,
    show_all: bool = False,
    threshold_enabled: bool = True,
    unpacking_date: Optional[Union[str, date]] = None,
    alerts_enabled: bool = True,
    customer_name: str = "",
) -> str:
    """Pretty-print a single report result for the text UI."""
    model, serial, dt_str = _report_header_fields(report)
    counters = getattr(report, "counters", {}) or {}
    counters_lines = _build_counter_lines(counters)
    combined = _combined_findings_for_text(selection, show_all)

    most_due_rows: List[str] = []
    for finding in combined:
        canon = getattr(finding, "canon", "—")
        pct = _fmt_pct(getattr(finding, "life_used", None))
        kit = getattr(finding, "kit_code", None) or "(N/A)"
        is_due = bool(getattr(finding, "due", False))
        if is_due:
            most_due_rows.append(f"  • {canon} — {pct} → DUE")
            most_due_rows.append(f"      ↳ Unit: {kit}")
        else:
            most_due_rows.append(f"  • {canon} — {pct}")
            most_due_rows.append("      ↳ Unit: (N/A)")
        most_due_rows.append("")

    final_lines: List[str] = []
    meta = getattr(selection, "meta", {}) or {}
    mandatory_alerts = _collect_mandatory_alerts(unpacking_date)
    optional_alerts = _collect_optional_alerts(meta) if alerts_enabled else []
    final_over, final_thr = _build_final_parts_lists(meta, threshold_enabled)

    over_rows = [f"{int(qty)}x → {pn} → {unit}" for qty, pn, unit in final_over]
    thr_rows = [f"{int(qty)}x → {pn} → {unit}" for qty, pn, unit in final_thr]

    inv_matches = meta.get("inventory_matches", []) or []
    inv_missing = meta.get("inventory_missing", []) or []

    final_lines.append("Final Parts — Over 100%")
    _append_separator_line(final_lines)
    final_lines.append("(Qty → Part Number → Unit )")
    final_lines.extend(over_rows if over_rows else ["(none)"])
    final_lines.append("")

    if thr_rows:
        final_lines.append("Final Parts — Threshold")
        _append_separator_line(final_lines)
        final_lines.append("(Qty → Part Number → Unit )")
        final_lines.extend(thr_rows)
        final_lines.append("")

    inv_lines = []
    if inv_matches:
        inv_lines.append("Inventory Matches (In Stock)")
        _append_separator_line(inv_lines)
        inv_lines.append("(Matched Code → Needed → In Stock)")
        for match in inv_matches:
            code = match.get("code")
            needed = int(match.get("needed", 0))
            stock = int(match.get("in_stock", 0))
            inv_lines.append(f"  ✓ {code} : Need {needed} | Have {stock}")
        inv_lines.append("")

    miss_lines = []
    if inv_missing:
        miss_lines.append("Items to Order (Missing from Stock)")
        _append_separator_line(miss_lines)
        miss_lines.append("(Code → Qty to Order)")
        for missing in inv_missing:
            code = missing.get("code")
            order_qty = int(missing.get("ordering", 0))
            note = missing.get("note", "")
            suffix = f" {note}" if note else ""
            miss_lines.append(f"  ! {code} : {order_qty}{suffix}")
        miss_lines.append("")

    lines: List[str] = []
    _append_separator_line(lines)
    lines.append(_build_header_line(model, serial, dt_str, unpacking_date))

    if customer_name:
        lines.append(f"Customer: {customer_name}")

    if mandatory_alerts:
        lines.append("")
        lines.append("!!! MANDATORY ALERTS !!!")
        for alert in mandatory_alerts:
            lines.append(f"  [!!] {alert}")
        lines.append("")

    if optional_alerts:
        lines.append("")
        lines.append("!!! SYSTEM ALERTS !!!")
        for alert in optional_alerts:
            lines.append(f"  [!] {alert}")
        lines.append("")

    thr_text = f"{threshold * 100:.1f}%" if threshold_enabled else "100.0%"
    lines.append(f"Due threshold: {thr_text}  •  Basis: {life_basis.upper()}")

    if counters_lines:
        lines.append("")
        lines.extend(counters_lines)

    lines.append("")
    lines.append("Highest Wear Items")
    _append_separator_line(lines)
    lines.extend(most_due_rows if most_due_rows else ["(none)", ""])

    lines.append("")
    lines.extend(final_lines)

    # Kept for future inventory output support; intentionally not appended today.
    # if inv_lines:
    #     lines.extend(inv_lines)
    # if miss_lines:
    #     lines.extend(miss_lines)

    lines.append("")
    _append_separator_line(lines)
    lines.append("End of Report")
    _append_separator_line(lines)

    return "\n".join(lines)


def create_pdf_report(
    *,
    report,
    selection,
    threshold: float,
    life_basis: str,
    show_all: bool = False,
    out_dir: str = ".",
    threshold_enabled: bool = True,
    unpacking_date: Optional[Union[str, date]] = None,
    alerts_enabled: bool = True,
    customer_name: str = "",
):
    model, serial, dt_str = _report_header_fields(report)

    counters = getattr(report, "counters", {}) or {}
    parts = _build_pdf_counter_parts(counters)

    combined = _combined_findings_for_pdf(selection, show_all)
    most_due: List[List[str]] = []
    for finding in combined:
        canon = getattr(finding, "canon", "—")
        pct = (getattr(finding, "life_used", None) or 0.0) * 100.0
        kit = getattr(finding, "kit_code", None) or "(N/A)"
        status = "DUE" if getattr(finding, "due", False) else ""
        most_due.append([canon, f"{pct:.1f}%", status, kit])

    meta = getattr(selection, "meta", {}) or {}
    mandatory_alerts = _collect_mandatory_alerts(unpacking_date)
    optional_alerts = _collect_optional_alerts(meta) if alerts_enabled else []
    final_over, final_thr = _build_final_parts_lists(meta, threshold_enabled)

    best_used_pct = (max((getattr(f, "life_used", None) or 0.0) for f in combined) * 100.0) if combined else 0.0
    model_trimmed = _extract_model_code(model)
    fname = f"{best_used_pct:.1f}_{serial}_{model_trimmed}.pdf"

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, fname)
    doc = SimpleDocTemplate(
        path,
        pagesize=LETTER,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    styles = _build_pdf_styles()

    story = []
    story.append(Paragraph(f"Model: {model}  |  Serial: {serial}  |  Last Reported: {dt_str}", styles["H1"]))
    if customer_name:
        story.append(Paragraph(f"Customer: {customer_name}", styles["Meta"]))
    if unpacking_date:
        story.append(Paragraph(f"Unpacking Date: {unpacking_date}", styles["Meta"]))

    story.append(_hline())
    thr_text = f"{threshold * 100:.1f}%" if threshold_enabled else "100.0%"
    story.append(Paragraph(f"Due threshold: {thr_text}  •  Basis: {life_basis.upper()}", styles["Meta"]))
    if parts:
        story.append(Paragraph("Counters: " + "  ".join(parts), styles["Meta"]))
    story.append(Spacer(1, 4))

    if mandatory_alerts:
        story.append(Paragraph("Mandatory Alerts", styles["MandatoryAlertHeader"]))
        for alert in mandatory_alerts:
            story.append(Paragraph(f"• {alert}", styles["MandatoryAlertText"]))
        story.append(Spacer(1, 4))
        story.append(_hline(thickness=1.0, color=colors.red))

    if optional_alerts:
        story.append(Paragraph("System Alerts", styles["AlertHeader"]))
        for alert in optional_alerts:
            story.append(Paragraph(f"• {alert}", styles["AlertText"]))
        story.append(Spacer(1, 4))
        story.append(_hline(thickness=0.5, color=colors.orange))

    if most_due:
        data = [["Canon", "Life Used", "Status", "Unit"]] + most_due
        tbl = Table(data, colWidths=[2.8 * inch, 0.95 * inch, 0.8 * inch, 2.05 * inch])
        _configure_table(
            tbl,
            len(data),
            [
                ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ("ALIGN", (2, 1), (2, -1), "CENTER"),
            ],
        )

        for row_idx in range(1, len(data)):
            try:
                val = float(most_due[row_idx - 1][1].strip("%"))
                tbl.setStyle(TableStyle([("TEXTCOLOR", (1, row_idx), (1, row_idx), _pct_color(val))]))
            except Exception:
                pass

        story.append(tbl)
    else:
        story.append(Paragraph("(none)", styles["Meta"]))

    story.append(Spacer(1, 4))
    story.append(Paragraph("Final Parts — Over 100%", styles["Section"]))
    story.append(_hline())

    if final_over:
        data = [["Qty", "Part Number", "Unit"]] + [[str(q), pn, unit] for q, pn, unit in final_over]
        tbl = Table(data, colWidths=[0.6 * inch, 3.0 * inch, 3.0 * inch])
        _configure_table(tbl, len(data), [("ALIGN", (0, 1), (0, -1), "RIGHT")])
        story.append(KeepTogether(tbl))
    else:
        story.append(Paragraph("(none)", styles["Meta"]))

    story.append(Spacer(1, 4))

    if final_thr:
        story.append(Paragraph("Final Parts — Threshold", styles["Section"]))
        story.append(_hline())
        data = [["Qty", "Part Number", "Unit"]] + [[str(q), pn, unit] for q, pn, unit in final_thr]
        tbl = Table(data, colWidths=[0.6 * inch, 3.0 * inch, 3.0 * inch])
        _configure_table(tbl, len(data), [("ALIGN", (0, 1), (0, -1), "RIGHT")])
        story.append(KeepTogether(tbl))

    doc.build(story)


def build_report_data(
    *,
    report: PmReport,
    selection,
    threshold: float,
    life_basis: str,
    show_all: bool = False,
    threshold_enabled: bool = True,
    unpacking_date: Optional[Union[str, date]] = None,
    alerts_enabled: bool = True,
    customer_name: str = "",
    error_records: Optional[list] = None,
) -> SingleReportData:
    """Build a structured SingleReportData from parsed report + rule selection."""
    model, serial, dt_str = _report_header_fields(report)
    counters = getattr(report, "counters", {}) or {}

    meta = getattr(selection, "meta", {}) or {}
    mandatory_alerts = _collect_mandatory_alerts(unpacking_date)
    optional_alerts = _collect_optional_alerts(meta) if alerts_enabled else []

    combined = _combined_findings_for_text(selection, show_all)

    findings: list[Finding] = []
    for f in combined:
        findings.append(Finding(
            canon=getattr(f, "canon", "—"),
            life_used=getattr(f, "life_used", None),
            due=bool(getattr(f, "due", False)),
            kit_code=getattr(f, "kit_code", None),
            qty=int(getattr(f, "qty", 1) or 1),
        ))

    due_count = sum(1 for f in findings if f.due)
    total_items = len(findings)
    ok_count = total_items - due_count
    highest_wear_pct = (max((f.life_used or 0.0) for f in findings) * 100.0) if findings else 0.0

    final_over_raw, final_thr_raw = _build_final_parts_lists(meta, threshold_enabled)
    final_over = [FinalPartEntry(qty=int(q), part_number=str(pn), unit=str(unit)) for q, pn, unit in final_over_raw]
    final_thr = [FinalPartEntry(qty=int(q), part_number=str(pn), unit=str(unit)) for q, pn, unit in final_thr_raw]

    unpack_str = ""
    if unpacking_date:
        if isinstance(unpacking_date, (date, datetime)):
            unpack_str = unpacking_date.strftime("%Y-%m-%d") if hasattr(unpacking_date, "strftime") else str(unpacking_date)
        else:
            unpack_str = str(unpacking_date)

    return SingleReportData(
        model=model,
        serial=serial,
        last_reported=dt_str,
        unpacking_date=unpack_str,
        customer_name=customer_name,
        threshold=threshold,
        threshold_enabled=threshold_enabled,
        life_basis=life_basis,
        mandatory_alerts=mandatory_alerts,
        optional_alerts=optional_alerts,
        counters=dict(counters) if counters else {},
        findings=findings,
        final_parts_over_100=final_over,
        final_parts_threshold=final_thr,
        error_records=error_records if error_records else [],
        due_count=due_count,
        ok_count=ok_count,
        total_items=total_items,
        highest_wear_pct=highest_wear_pct,
    )


def generate_from_bytes(
    pm_pdf_bytes: bytes,
    threshold: float,
    life_basis: str,
    show_all: bool = False,
    threshold_enabled: bool = True,
    unpacking_date: Optional[Union[str, date]] = None,
    alerts_enabled: bool = True,
    customer_name: str = "",
) -> str:
    report: PmReport = parse_pm_report(pm_pdf_bytes)
    selection = run_rules(
        report,
        threshold=threshold,
        life_basis=life_basis,
        threshold_enabled=threshold_enabled,
    )
    return format_report(
        report=report,
        selection=selection,
        threshold=threshold,
        life_basis=life_basis,
        show_all=show_all,
        threshold_enabled=threshold_enabled,
        unpacking_date=unpacking_date,
        alerts_enabled=alerts_enabled,
        customer_name=customer_name,
    )