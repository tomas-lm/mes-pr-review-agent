from enum import StrEnum

from pydantic import BaseModel, Field


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    COMMENT = "comment"
    REQUEST_CHANGES = "request_changes"
    SKIP = "skip"


class FindingSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NIT = "nit"


class FindingCategory(StrEnum):
    BUG = "bug"
    SECURITY = "security"
    TEST = "test"
    MAINTAINABILITY = "maintainability"
    STYLE = "style"
    SPEC = "spec"


class ReviewFinding(BaseModel):
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    category: FindingCategory
    path: str
    line: int | None = None
    side: str | None = Field(default=None, pattern="^(LEFT|RIGHT)$")
    title: str
    body: str
    evidence: list[str] = Field(default_factory=list)
    suggested_fix: str | None = None


class ReviewPayload(BaseModel):
    decision: ReviewDecision
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
