import re
from PyQt6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont
from pmgen.ui.theme import OUTPUT_HIGHLIGHT_COLORS

class OutputHighlighter(QSyntaxHighlighter):
    def __init__(self, parent_doc):
        super().__init__(parent_doc)
        
        # 1. Build Text Formats
        self._build_formats()
        
        # 2. Compile Regex Patterns (Performance Optimization)
        # Bulk patterns
        self.re_bulk_pct = re.compile(r"(?P<num>\d+(?:\.\d+)?)%")
        self.re_bulk_ok = re.compile(r"\bOK\b", re.IGNORECASE)
        self.re_bulk_filtered = re.compile(r"\bFILTERED\b", re.IGNORECASE)
        self.re_bulk_serial = re.compile(r"\b[A-Z0-9]{5,10}\b")
        
        # Kit patterns
        self.re_kit_new_after = re.compile(r"^\s*(?P<qty>\d+)\s*[x×]\s*→\s*(?P<pn>\S+)\s*→\s*(?P<kit>\S.*?)\s*$", re.IGNORECASE)
        self.re_kit_new_before = re.compile(r"^\s*x\s*(?P<qty>\d+)\s*→\s*(?P<pn>\S+)\s*→\s*(?P<kit>\S.*?)\s*$", re.IGNORECASE)
        self.re_kit_old = re.compile(r"^\s*(?P<kit>\S.*?)\s*→\s*(?P<pn>\S+)\s*[×x]\s*(?P<qty>\d+)\s*$", re.IGNORECASE)
        
        # Due item pattern
        self.re_due_item = re.compile(r"^\s*•\s+(?P<canon>.+?)\s+—\s+(?P<pct>\S+)(?:\s*→\s*(?P<due>DUE))?\s*$")
        
        self.re_customer_info = re.compile(r"^\s*Customer:\s*(?P<customer>.+)$")

        # Model info pattern
        self.re_model_info = re.compile(
            r"Model:\s*(?P<model>.*?)(?=\s+\|)\s*\|\s*"
            r"Serial:\s*(?P<serial>\S+)\s*\|\s*"
            r"Last Reported:\s*(?P<report_date>.*?)(?=\s+\|)\s*\|\s*"
            r"Unpacking Date:\s*(?P<unpacking_date>.+)$"
        )
        
        # Threshold pattern
        self.re_threshold = re.compile(
            r"(?i)"
            r"(?P<label>due\s*threshold:)\s*"   # 'Due threshold:'
            r"(?P<thresh>[0-9.]+%?)\s*"         # '94.0%'
            r"(?P<sep>•)\s*"                    # '•'
            r"(?P<basis_lab>basis:)\s*"         # 'Basis:'
            r"(?P<basis>\S+)"                   # 'PAGE'
        )
        
        # Counter pattern (key: value)
        self.re_kv_pair = re.compile(r"([A-Za-z]+):\s*([0-9,]+)")

    def _mkfmt(self, fg=None, bold=False, italic=False):
        """Helper to create a QTextCharFormat."""
        fmt = QTextCharFormat()
        if fg is not None:
            fmt.setForeground(QColor(fg))
        if bold:
            fmt.setFontWeight(QFont.Weight.DemiBold)
        if italic:
            fmt.setFontItalic(True)
        return fmt

    def _build_formats(self):
        """Initialize all text styles."""
        colors = OUTPUT_HIGHLIGHT_COLORS
        self.fmt_normal = self._mkfmt(colors["normal"], bold=True)
        self.fmt_muted = self._mkfmt(colors["muted"], italic=True)
        self.fmt_header = self._mkfmt(colors["header"], bold=True)
        self.fmt_rule = self._mkfmt(colors["rule"])
        self.fmt_info = self._mkfmt(colors["info"], bold=True)
        self.fmt_label = self._mkfmt(colors["label"], bold=True)
        self.fmt_alert = self._mkfmt(colors["alert"], bold=True)
        self.fmt_customer_value = self._mkfmt(colors["customer_value"], bold=True)
        self.fmt_bulk = self._mkfmt(colors["bulk"], bold=True)
        self.fmt_bulk_serial = self._mkfmt(colors["bulk_serial"], bold=True)
        self.fmt_bulk_ok = self._mkfmt(colors["bulk_ok"], bold=True)
        self.fmt_bulk_filtered = self._mkfmt(colors["bulk_filtered"], bold=True)
        self.fmt_pct_low = self._mkfmt(colors["pct_low"], bold=True)
        self.fmt_pct_mid = self._mkfmt(colors["pct_mid"], bold=True)
        self.fmt_pct_high = self._mkfmt(colors["pct_high"], bold=True)
        self.fmt_kit_row = self._mkfmt(colors["kit_row"])
        self.fmt_due_bullet = self._mkfmt(colors["due_bullet"], bold=True)
        self.fmt_due_row_base = self._mkfmt(colors["due_row_base"])
        self.fmt_due_canon = self._mkfmt(colors["due_canon"], bold=True)
        self.fmt_due_pct = self._mkfmt(colors["due_pct"], bold=True)
        self.fmt_due_flag = self._mkfmt(colors["due_flag"], bold=True)
        self.fmt_model_value = self._mkfmt(colors["model_value"], bold=True)
        self.fmt_serial_value = self._mkfmt(colors["serial_value"], bold=True)
        self.fmt_r_date_value = self._mkfmt(colors["report_date"])
        self.fmt_u_date_value = self._mkfmt(colors["unpacking_date"])
        self.fmt_badge_line_base = self._mkfmt(colors["badge_line_base"])
        self.fmt_thresh_value = self._mkfmt(colors["threshold_value"], bold=True)
        self.fmt_basis_badge = self._mkfmt(colors["basis_badge"], bold=True)
        self.fmt_counters_base = self._mkfmt(colors["counters_base"])
        self.fmt_kv_label = self._mkfmt(colors["kv_label"], bold=True)
        self.fmt_kv_value = self._mkfmt(colors["kv_value"], bold=True)

    def highlightBlock(self, text: str | None):
        """Main entry point for syntax highlighting."""
        if text is None:
            return
        # 1. Apply base normal format to the whole line
        self.setFormat(0, len(text), self.fmt_normal)

        t = text.strip()
        if not t:
            return

        # --- Priority Tags ---
        if "[Auto-Login]" in t:
            self.setFormat(0, len(text), self.fmt_muted)
            return
        
        if "[Info]" in t:
            self.setFormat(0, len(text), self.fmt_info)
            # We don't return here as [Info] might have other content, 
            # though usually it's standalone. If standalone, add 'return'.

        # --- Bulk Handling (Complex Logic) ---
        if "[Bulk]" in t:
            self._highlight_bulk_line(text, t)
            return

        # --- Unpack Alert ---
        if "[!] Unpacking Date Alert:" in t:
            self.setFormat(0, len(text), self.fmt_alert)
            return

        # --- Standard Headers & Rules ---
        if t in ("Final Parts", "Most-Due Items", "Counters", "End of Report"):
            self.setFormat(0, len(text), self.fmt_header)
            return

        # Check for horizontal rules (e.g. "----", "====")
        # Checks if all unique characters in the string are part of the rule set
        unique_chars = set(t)
        if unique_chars == {"─"} or unique_chars == {"-"} or unique_chars == {"="}:
            self.setFormat(0, len(text), self.fmt_rule)
            return

        # --- Muted / specific prefixes ---
        t_lower = t.lower()
        if t.startswith("(") and any(tok in t_lower for tok in ("qty", "catalog", "part number", "×", " x ")):
            self.setFormat(0, len(text), self.fmt_muted)
            return

        # --- Kit / Part Rows ---
        if "→" in t and not t.startswith("Report Date"):
            if (self.re_kit_new_after.match(t) or 
                self.re_kit_new_before.match(t) or 
                self.re_kit_old.match(t)):
                self.setFormat(0, len(text), self.fmt_kit_row)
                return

        # --- Due Items / Bullets ---
        if t.startswith("• ") or "→ DUE" in t:
            self._highlight_due_item(text, t)
            return

        # --- Model Info Block ---
        if t.startswith("Model:") and "Serial:" in t:
            self._highlight_model_info(text)
            return
        
        # --- Customer Info ---
        if t.startswith("Customer:"):
            self._highlight_customer(text)
            return

        # --- Labels ---
        if t.startswith("Basis:") or t.startswith("Report Date:"):
            self.setFormat(0, len(text), self.fmt_label)
            return

        # --- Thresholds ---
        if t_lower.startswith("due threshold:") and "basis:" in t_lower:
            self._highlight_threshold(text)
            return

        # --- Counters ---
        if t_lower.startswith("color:") or (" black:" in t_lower and " total:" in t_lower):
            self._highlight_counters(text)
            return

    def _highlight_bulk_line(self, text, stripped):
        """Handles specific formatting for lines containing [Bulk]."""
        # 1. Color the [Bulk] tag itself
        tag_bulk = "[Bulk]"
        start_index = text.find(tag_bulk)
        if start_index >= 0:
            self.setFormat(start_index, len(tag_bulk), self.fmt_bulk)

        # 2. Color Percentages based on value
        for m in self.re_bulk_pct.finditer(stripped):
            try:
                val = float(m.group("num"))
                if val < 84.0:
                    fmt = self.fmt_pct_low
                elif val < 100.0:
                    fmt = self.fmt_pct_mid
                else:
                    fmt = self.fmt_pct_high
                self.setFormat(m.start(), m.end() - m.start(), fmt)
            except ValueError:
                continue

        # 3. Status Keywords
        for m in self.re_bulk_ok.finditer(stripped):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bulk_ok)

        for m in self.re_bulk_filtered.finditer(stripped):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bulk_filtered)

        # 4. Serial Numbers
        for m in self.re_bulk_serial.finditer(stripped):
            self.setFormat(m.start(), m.end() - m.start(), self.fmt_bulk_serial)

    def _highlight_customer(self, text):
        """Handles the Customer Name line."""
        m = self.re_customer_info.search(text)
        if m:            
            self.setFormat(m.start("customer"), m.end("customer") - m.start("customer"), self.fmt_customer_value)

    def _highlight_due_item(self, text, stripped):
        """Handles lines with bullets or DUE flags."""
        m = self.re_due_item.match(stripped)
        if m:
            self.setFormat(0, len(text), self.fmt_due_row_base)
            
            left_ws = len(text) - len(text.lstrip())

            def _apply(name, fmt):
                if m.group(name):
                    s, e = m.start(name), m.end(name)
                    self.setFormat(left_ws + s, e - s, fmt)

            _apply("canon", self.fmt_due_canon)
            _apply("pct",   self.fmt_due_pct)
            if m.group("due"):
                _apply("due", self.fmt_due_flag)
        else:
            self.setFormat(0, len(text), self.fmt_due_bullet)

    def _highlight_model_info(self, text):
        """Handles the Model | Serial | Date line."""
        m = self.re_model_info.search(text)
        if m:
            self.setFormat(m.start("model"), m.end("model") - m.start("model"), self.fmt_model_value)
            self.setFormat(m.start("serial"), m.end("serial") - m.start("serial"), self.fmt_serial_value)
            self.setFormat(m.start("report_date"), m.end("report_date") - m.start("report_date"), self.fmt_r_date_value)
            self.setFormat(m.start("unpacking_date"), m.end("unpacking_date") - m.start("unpacking_date"), self.fmt_u_date_value)

    def _highlight_threshold(self, text):
        """Handles the Due Threshold line with granular coloring."""
        m = self.re_threshold.search(text)
        if m:
            self.setFormat(*m.span("thresh"), self.fmt_thresh_value)
            self.setFormat(*m.span("sep"), self.fmt_normal)
            self.setFormat(*m.span("basis_lab"), self.fmt_normal)
            self.setFormat(*m.span("basis"), self.fmt_basis_badge)

    def _highlight_counters(self, text):
        """Handles Key:Value lines (Colors, counts)."""
        self.setFormat(0, len(text), self.fmt_counters_base)
        for m in self.re_kv_pair.finditer(text):
            self.setFormat(*m.span(1), self.fmt_kv_label)
            self.setFormat(*m.span(2), self.fmt_kv_value)
