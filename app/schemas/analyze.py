"""Schemas for the analyze dashboard endpoint."""

from typing import List

from pydantic import BaseModel, Field

from .common import BadgeTypeEnum, ToneEnum


class AnalyzeRequest(BaseModel):
    user_name: str = Field(..., description="사용자 이름")
    age: int = Field(..., ge=0, description="사용자 나이")
    region: str = Field(..., description="거주 지역")
    income_percent: float = Field(..., ge=0, description="중위소득 비율")
    household_type: str = Field(..., description="가구 형태")
    employment_status: str = Field(..., description="취업 상태")
    education_level: str = Field(..., description="학력")
    language: str = Field(default="ko", description="응답 언어")


class UserProfile(BaseModel):
    user_name: str
    updated_at_label: str
    region_label: str
    total_score: int
    score_max: int
    tags: List[str]


class ConditionCurrentValues(BaseModel):
    age_label: str
    region: str
    income_label: str
    household_type: str
    employment_status: str
    education_level: str


class ConditionForm(BaseModel):
    current_values: ConditionCurrentValues


class RecommendationBadge(BaseModel):
    type: BadgeTypeEnum
    label: str


class RecommendationCard(BaseModel):
    policy_id: str
    icon: str
    policy_name: str
    subtitle: str
    badges: List[RecommendationBadge]
    eligibility_percent: int
    benefit_label: str
    tone: ToneEnum
    detail_target_id: str


class DashboardStats(BaseModel):
    matched_policy_count: int
    average_probability_percent: int
    expected_total_benefit_label: str
    ready_apply_count: int


class PortfolioPreviewItem(BaseModel):
    icon: str
    label: str
    benefit_label: str


class PortfolioPreview(BaseModel):
    total_expected_benefit_label: str
    items: List[PortfolioPreviewItem]


class DashboardData(BaseModel):
    user_profile: UserProfile
    condition_form: ConditionForm
    recommendation_cards: List[RecommendationCard]
    dashboard_stats: DashboardStats
    portfolio_preview: PortfolioPreview


class AnalyzeResponse(BaseModel):
    query_id: str
    dashboard_data: DashboardData
