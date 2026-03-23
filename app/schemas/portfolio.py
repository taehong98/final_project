"""Schemas for portfolio endpoints."""

from typing import List

from pydantic import BaseModel

from .common import PolicyStatusEnum


class PortfolioHero(BaseModel):
    total_expected_benefit_label: str
    portfolio_basis_label: str
    ready_count: int
    conditional_count: int


class PortfolioItem(BaseModel):
    policy_id: str
    icon: str
    policy_name: str
    expected_benefit_label: str
    benefit_period_label: str
    status: PolicyStatusEnum


class PortfolioCTA(BaseModel):
    headline: str
    description: str
    apply_assist_enabled: bool


class PortfolioData(BaseModel):
    portfolio_hero: PortfolioHero
    portfolio_items: List[PortfolioItem]
    portfolio_cta: PortfolioCTA


class PortfolioResponse(BaseModel):
    portfolio_data: PortfolioData
