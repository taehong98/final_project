from pydantic import BaseModel, Field

from app.schemas.common import PolicySummary


class PolicySearchData(BaseModel):
    items: list[PolicySummary] = Field(default_factory=list)
    query: str
    total_count: int
