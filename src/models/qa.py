from __future__ import annotations

from typing import Optional
from typing import Literal

from pydantic import BaseModel


class QAIssue(BaseModel):
    severity: Literal["info", "warn", "error"]
    code: str
    message: str
    location: Optional[str] = None
    suggested_fix: Optional[str] = None
