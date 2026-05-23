from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Pattern:
    name: str
    confidence: float  # 0.0 – 1.0
    label: str
    details: dict[str, Any] = field(default_factory=dict)
