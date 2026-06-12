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
