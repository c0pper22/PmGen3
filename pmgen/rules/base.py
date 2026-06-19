from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any
from pmgen.types import PmReport, PmItem, Finding

@dataclass
class Context:
    report: PmReport
    model: str
    items_by_canon: Dict[str, List[PmItem]]
    threshold: float
    life_basis: str
    counters: Dict[str, int] = field(default_factory=dict)
    threshold_enabled: bool = False
    findings: Dict[str, Finding] = field(default_factory=dict)
    kit_selection: Dict[str, int] = field(default_factory=dict)
    mandatory_alerts: List[str] = field(default_factory=list)
    optional_alerts: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

class RuleBase:
    name: str = "RuleBase"
    
    def apply(self, ctx: Context) -> None:
        raise NotImplementedError