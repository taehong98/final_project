from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field


T = TypeVar("T")


class IncomeBand(str, Enum):
    MID_50_60 = "MID_50_60"
    MID_60_80 = "MID_60_80"
    MID_80_100 = "MID_80_100"


class HouseholdType(str, Enum):
    SINGLE = "SINGLE"
    TWO_PERSON = "TWO_PERSON"
    MULTI_PERSON = "MULTI_PERSON"


class EmploymentStatus(str, Enum):
    UNEMPLOYED = "UNEMPLOYED"
    EMPLOYED = "EMPLOYED"
    SELF_EMPLOYED = "SELF_EMPLOYED"


class HousingStatus(str, Enum):
    MONTHLY_RENT = "MONTHLY_RENT"
    JEONSE = "JEONSE"
    OWNER_FAMILY_HOME = "OWNER_FAMILY_HOME"


class ScoreLevel(str, Enum):
    HIGH = "HIGH"
    MID = "MID"
    LOW = "LOW"


class ApplyStatus(str, Enum):
    APPLICABLE_NOW = "APPLICABLE_NOW"
    NEEDS_CHECK = "NEEDS_CHECK"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


class DocumentStatus(str, Enum):
    READY = "READY"
    MISSING = "MISSING"
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"


class ApplicationStep(str, Enum):
    PROFILE_INPUT = "PROFILE_INPUT"
    AI_ANALYSIS = "AI_ANALYSIS"
    POLICY_SELECTION = "POLICY_SELECTION"
    DOCUMENT_PREP = "DOCUMENT_PREP"
    SUBMITTED = "SUBMITTED"


class Meta(BaseModel):
    request_id: str = Field(default_factory=lambda: f"req_{uuid4().hex[:12]}")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SuccessResponse(BaseModel, Generic[T]):
    success: bool = True
    data: T
    meta: Meta = Field(default_factory=Meta)


class ErrorDetail(BaseModel):
    field: str
    reason: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    success: bool = False
    error: ErrorBody
    meta: Meta = Field(default_factory=Meta)


class PolicySummary(BaseModel):
    policy_id: str
    title: str
    description: str | None = None
    match_score: int
    score_level: ScoreLevel
    apply_status: ApplyStatus
    benefit_amount: int | None = None
    benefit_amount_label: str | None = None
    benefit_summary: str | None = None
    badge_items: list[str] = Field(default_factory=list)
    sort_order: int


class UnmatchedPolicyItem(BaseModel):
    reference_id: str
    source: str | None = None
    reason: str = "NOT_IN_DB"


class PolicyLinkItem(BaseModel):
    link_type: str
    link_name: str | None = None
    link_url: str
    sort_order: int


class PolicyLawItem(BaseModel):
    law_name: str
    law_type: str | None = None
    source: str | None = None


class PolicyTagItem(BaseModel):
    tag_type: str
    tag_code: str
    tag_label: str


class RequiredDocumentItem(BaseModel):
    document_type: str
    document_name: str
    status: DocumentStatus | None = None
    description: str | None = None
    is_required: bool
    issued_within_days: int | None = None
    uploaded_file_url: str | None = None
    verified_at: datetime | None = None


class ChecklistItem(BaseModel):
    code: str
    label: str
    is_done: bool
    sort_order: int
