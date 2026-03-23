"""Schemas for policy detail endpoints."""

from typing import List

from pydantic import BaseModel


class PolicyHeader(BaseModel):
    policy_id: str
    icon: str
    policy_name: str
    eligibility_percent: int
    progress_color: str


class IssueItem(BaseModel):
    issue_id: str
    icon: str
    title: str
    description: str


class GuideItem(BaseModel):
    step: int
    title: str
    description: str


class SummaryStats(BaseModel):
    annual_benefit_label: str
    processing_period_label: str
    issue_count: int


class DetailActions(BaseModel):
    apply_assist_enabled: bool
    back_to_dashboard_enabled: bool


class DetailData(BaseModel):
    policy_header: PolicyHeader
    issues: List[IssueItem]
    guides: List[GuideItem]
    summary_stats: SummaryStats
    actions: DetailActions


class DetailResponse(BaseModel):
    detail_data: DetailData
