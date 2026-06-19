from pmgen.canon.canon_utils import canon_unit
import csv
import re
from typing import Optional, List

class PmItem:
    def __init__(self, descriptor = None, current_page_count = None, expected_page_count = None, current_drive_count = None, expected_drive_count = None):
        self.descriptor = descriptor
        self.canon = canon_unit(descriptor)
        self.counts = { "page": {
                            "current": current_page_count,
                            "expected": expected_page_count
                        },
                        "drive": {
                            "current": current_drive_count,
                            "expected": expected_drive_count
                        }
                      }
        
    def _safe_ratio(self, num, den):
        try:
            if den in (0, None) or num is None:
                return None
            return num / den
        except Exception:
            return None
        
    def getPageLifePercent(self):
        return self._safe_ratio(self.counts["page"]["current"], self.counts["page"]["expected"])
    
    def getDriveLifePercent(self):
        return self._safe_ratio(self.counts["drive"]["current"], self.counts["drive"]["expected"])
        
    def __repr__(self):
        return (
            f"{self.descriptor}\n"
            f"  {self.canon}\n"
            f"      Page Life: {self.getPageLifePercent()}\n"
            f"      Drive Life: {self.getDriveLifePercent()}\n"
        )
    @property
    def page_current(self):
        return self.counts["page"]["current"]

    @property
    def page_expected(self):
        return self.counts["page"]["expected"]

    @property
    def drive_current(self):
        return self.counts["drive"]["current"]

    @property
    def drive_expected(self):
        return self.counts["drive"]["expected"]

    @property
    def page_life(self):
        # fraction used (0.0–inf) or None
        return self.getPageLifePercent()

    @property
    def drive_life(self):
        # fraction used (0.0–inf) or None
        return self.getDriveLifePercent()

class PmReport:
    def __init__(self, headers = None, counters = None, items = None):
        self.headers = headers
        self.counters = counters
        self.items = items
    
    def __repr__(self):
        header_stdout = (
            f"Headers:\n"
            f"  Title: {self.headers.get('title', '-')}\n"
            f"  Report Date: {self.headers.get('date', '-')}\n"
            f"  Model: {self.headers.get('model', '-')}\n"
            f"  Serial Number: {self.headers.get('serial', '-')}\n"
            f"  Finisher: {self.headers.get('fin', '-')}\n"
        )

        counters_stdout = (
            f"Counters:\n"
            f"  Color: {self.counters.get('color', '-')}\n"
            f"  Black: {self.counters.get('black', '-')}\n"
            f"  Total: {self.counters.get('total', '-')}\n"
            f"  DF: {self.counters.get('df', '-')}\n"
        )

        items_stdout = "Items:\n\n  " + "\n  ".join(repr(item) for item in self.items) if self.items else "Items: (none)"

        return "\n".join([header_stdout, counters_stdout, items_stdout])

def ParsePmReport(data: bytes) -> PmReport:
    # ---------------- helpers ----------------
    def clean_lines(b: bytes) -> List[str]:
        txt = b.decode("utf-8", errors="ignore")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n")
        # keep only non-empty, stripped lines
        return [ln.strip() for ln in txt.split("\n") if ln.strip()]

    def to_int(s: Optional[str]) -> Optional[int]:
        if s is None:
            return None
        s = s.strip()
        if not s:
            return None
        s_digits = re.sub(r"[^\d]", "", s)
        if not s_digits:
            return None
        try:
            return int(s_digits)
        except ValueError:
            return None

    lines = clean_lines(data)
    if len(lines) < 5:
        raise ValueError("PM text too short or malformed: missing required header lines.")

    # ---------------- header detection ----------------
    # Title: prefer the PM SUPPORT header if present
    title = next((ln for ln in lines[:5] if ln.upper().startswith("PM SUPPORT CODE LIST")), lines[0])

    date_pat = re.compile(
            r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})"
            r"|(\d{4}[-/]\d{1,2}[-/]\d{1,2})"
        )
    
    report_date = ""
    for ln in lines[:6]:
        match = date_pat.search(ln)
        if match:
            report_date = match.group(0)
            break

    # Model: look for e-STUDIO ####AC in the first few lines
    model_pat = re.compile(r"e[-\s]?studio\s*\d{4,5}ac", re.I)
    model = next((ln for ln in lines[:10] if model_pat.search(ln)), "")
    if not model and len(lines) > 2:
        model = lines[2]

    # Serial: match common Toshiba serial pattern (e.g., CNAM66582)
    serial_pat = re.compile(r"\b[A-Z][A-Z0-9]{3}\d{5}\b", re.I)
    serial = next((ln for ln in lines[:10] if serial_pat.search(ln)), "")
    if serial:
        # If the line contains extra text, extract just the serial token
        m = serial_pat.search(serial)
        serial = m.group(0) if m else serial
    elif len(lines) > 3:
        serial = lines[3]

    # Finisher: optional "FIN S/N-" line
    fin = ""
    fin_line = next((ln for ln in lines[:12] if ln.upper().startswith("FIN S/N-")), "")
    if fin_line:
        m = re.match(r"^FIN S/N-(.*)$", fin_line.strip(), re.I)
        fin = (m.group(1).strip() if m and m.group(1).strip() else "")

    # ---------------- counters ----------------
    # Find the line that starts with TOTAL (may not be immediately after serial/fin)
    idx_total = next((i for i, ln in enumerate(lines) if ln.startswith("TOTAL")), None)
    if idx_total is None:
        # sometimes the file has minor noise; look a little fuzzier
        idx_total = next((i for i, ln in enumerate(lines) if ln.upper().startswith("TOTAL")), None)
    if idx_total is None:
        raise ValueError("Missing TOTAL counters line.")

    counter_parts = [part.strip() for part in lines[idx_total].split(",")]
    # Layout: TOTAL, [1]=color, [2]=ignore, [3]=black, [4]="DF TOTAL", [5]=df
    color = to_int(counter_parts[1] if len(counter_parts) > 1 else None)
    black = to_int(counter_parts[3] if len(counter_parts) > 3 else None)
    df    = to_int(counter_parts[5] if len(counter_parts) > 5 else None)
    total = (color or 0) + (black or 0)
    counters = {"color": color, "black": black, "df": df, "total": total}

    # ---------------- UNIT header ----------------
    # Find the UNIT column header line explicitly
    idx_unit_hdr = next((i for i, ln in enumerate(lines[idx_total:idx_total+10], start=idx_total) if ln.startswith("UNIT")), None)
    if idx_unit_hdr is None:
        # search more broadly if needed
        idx_unit_hdr = next((i for i, ln in enumerate(lines) if ln.startswith("UNIT")), None)
    if idx_unit_hdr is None:
        raise ValueError("Missing UNIT header line.")

    # ---------------- items ----------------
    items: List[PmItem] = []
    for k in range(idx_unit_hdr + 1, len(lines)):
        row = lines[k]
        if row.startswith("PM SUPPORT CODE LIST") or row.startswith("UNIT,"):
            continue

        reader = csv.reader([row])
        parts = [p.strip() for p in next(reader)]
        if not parts:
            continue

        descriptor = parts[0]
        page_cur  = to_int(parts[1] if len(parts) > 1 else None)
        page_exp  = to_int(parts[2] if len(parts) > 2 else None)
        drive_cur = to_int(parts[3] if len(parts) > 3 else None)
        drive_exp = to_int(parts[4] if len(parts) > 4 else None)

        items.append(PmItem(descriptor, page_cur, page_exp, drive_cur, drive_exp))

    headers = {
        "title": title,
        "date": report_date,
        "model": model or "Unknown",
        "serial": serial or "Unknown",
        "fin": fin,
    }

    return PmReport(headers=headers, counters=counters, items=items)


# alias for engine
parse_pm_report = ParsePmReport