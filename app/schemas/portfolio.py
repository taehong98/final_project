from pydantic import BaseModel, Field

from app.schemas.common import ApplyStatus, PolicyTagItem


class PortfolioItem(BaseModel):
    policy_id: str
    title: str
    amount: int | None = None
    amount_label: str | None = None
    period_label: str | None = None
    apply_status: ApplyStatus
    source: str | None = None
    managing_agency: str | None = None
    benefit_summary: str | None = None
    application_url: str | None = None
    tags: list[PolicyTagItem] = Field(default_factory=list)
    sort_order: int


class PortfolioData(BaseModel):
    total_estimated_benefit_amount: int
    total_estimated_benefit_label: str
    currency: str = "KRW"
    selected_policy_count: int
    applicable_now_count: int
    needs_check_count: int
    portfolio_items: list[PortfolioItem]
