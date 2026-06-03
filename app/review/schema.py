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


class CheckConclusion(StrEnum):
    SUCCESS = "success"
    NEUTRAL = "neutral"
    FAILURE = "failure"


class PullRequestReviewEvent(StrEnum):
    APPROVE = "APPROVE"
    COMMENT = "COMMENT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class DiscardReason(StrEnum):
    INVALID_SCHEMA = "invalid_schema"
    LOW_CONFIDENCE = "low_confidence"
    MISSING_EVIDENCE = "missing_evidence"
    PATH_NOT_IN_PR = "path_not_in_pr"
    LINE_NOT_IN_DIFF = "line_not_in_diff"
    LINE_NOT_CHANGED = "line_not_changed"
    INVALID_SIDE = "invalid_side"
    DUPLICATE = "duplicate"
    INTERNAL_REASONING = "internal_reasoning"
    SECRET_DETECTED = "secret_detected"
    CONTEXT_UNAVAILABLE = "context_unavailable"


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


class DiscardedFinding(BaseModel):
    reason: DiscardReason
    finding: dict
    detail: str | None = None


class ValidatedReviewPayload(BaseModel):
    decision: ReviewDecision
    publishable_findings: list[ReviewFinding] = Field(default_factory=list)
    summary_findings: list[ReviewFinding] = Field(default_factory=list)
    discarded_findings: list[DiscardedFinding] = Field(default_factory=list)
    check_conclusion: CheckConclusion
    review_event: PullRequestReviewEvent
