"""Common schema types shared across API domains."""

from enum import Enum

from pydantic import BaseModel, Field


class ToneEnum(str, Enum):
    top = "top"
    mid = "mid"
    low = "low"


class PolicyStatusEnum(str, Enum):
    ready = "ready"
    conditional = "conditional"
    blocked = "blocked"


class StepStatusEnum(str, Enum):
    done = "done"
    active = "active"
    todo = "todo"


class DocumentStatusEnum(str, Enum):
    ready = "ready"
    missing = "missing"
    review = "review"


class BadgeTypeEnum(str, Enum):
    success = "success"
    source = "source"
    benefit = "benefit"


class ErrorResponse(BaseModel):
    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
