from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Dict, List

@dataclass
class Finding:
    canon: str
    life_used: Optional[float] = None
    due: bool = False
    kit_code: str | None = None
    qty: int = 1
    
    def __repr__(self):
        return f"Finding({self.canon}, {self.life_used}, due={self.due})"

@dataclass
class Selection:
    items: List[Finding] = field(default_factory=list)
    kits: List[Dict[str, str]] = field(default_factory=list)
    meta: Dict[str, object] = field(default_factory=dict)  

@dataclass
class PmItem:
    descriptor: str
    page_current: Optional[int] = None
    page_expected: Optional[int] = None
    drive_current: Optional[int] = None
    drive_expected: Optional[int] = None
    canon: Optional[str] = None

    def _safe_ratio(self, n, d):
        try:
            if d in (0, None) or n is None:
                return None
            return n / d
        except Exception:
            return None

    @property
    def page_life(self) -> Optional[float]:
        return self._safe_ratio(self.page_current, self.page_expected)

    @property
    def drive_life(self) -> Optional[float]:
        return self._safe_ratio(self.drive_current, self.drive_expected)

@dataclass
class PmReport:
    headers: Dict[str, str] = field(default_factory=dict)
    counters: Dict[str, Optional[int]] = field(default_factory=dict)
    items: List[PmItem] = field(default_factory=list)


@dataclass
class FinalPartEntry:
    """A single row in a Final Parts list."""
    qty: int
    part_number: str
    unit: str


@dataclass
class SingleReportData:
    """Structured data for a single-report generation, consumed by widget-based UI."""
    model: str = ""
    serial: str = ""
    last_reported: str = ""
    unpacking_date: str = ""
    customer_name: str = ""
    threshold: float = 0.80
    threshold_enabled: bool = True
    life_basis: str = "page"
    alerts: List[str] = field(default_factory=list)
    counters: Dict[str, object] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    final_parts_over_100: List[FinalPartEntry] = field(default_factory=list)
    final_parts_threshold: List[FinalPartEntry] = field(default_factory=list)
    due_count: int = 0
    ok_count: int = 0
    total_items: int = 0
    highest_wear_pct: float = 0.0
