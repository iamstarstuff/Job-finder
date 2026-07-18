from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Job:
    company: str
    title: str
    url: str
    portal_url: str
    closing_date: Optional[str] = None
    sector: str = "pharma"

    @property
    def key(self) -> str:
        return self.url or f"{self.company}::{self.title}"
