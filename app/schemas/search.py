from pydantic import BaseModel, Field

from app.schemas.common import PolicySummary, UnmatchedPolicyItem


class PolicySearchData(BaseModel):
    items: list[PolicySummary] = Field(default_factory=list)
    query: str
    total_count: int
    rag_answer: str | None = None
    rag_docs_used: list[str] = Field(default_factory=list)
    unmatched_policies: list[UnmatchedPolicyItem] = Field(default_factory=list)
