from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RawApiFetchLog(Base):
    __tablename__ = "raw_api_fetch_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    endpoint_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    request_params_json: Mapped[dict | None] = mapped_column(JSON)
    response_status_code: Mapped[int | None] = mapped_column(Integer)
    response_meta_json: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    success_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawPolicyListItem(Base):
    __tablename__ = "raw_policy_list_item"
    __table_args__ = (
        UniqueConstraint("source", "source_policy_id", "raw_hash", name="uq_raw_policy_list_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_policy_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    page_no: Mapped[int | None] = mapped_column(Integer)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class RawPolicyDetailItem(Base):
    __tablename__ = "raw_policy_detail_item"
    __table_args__ = (
        UniqueConstraint("source", "source_policy_id", "raw_hash", name="uq_raw_policy_detail_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_policy_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class RawPolicyConditionItem(Base):
    __tablename__ = "raw_policy_condition_item"
    __table_args__ = (
        UniqueConstraint("source", "source_policy_id", "raw_hash", name="uq_raw_policy_condition_item"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_policy_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class RawPolicySubresourceItem(Base):
    __tablename__ = "raw_policy_subresource_item"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_policy_id",
            "subresource_type",
            "raw_hash",
            name="uq_raw_policy_subresource_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_policy_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    subresource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class PolicyMaster(Base):
    __tablename__ = "policy_master"
    __table_args__ = (UniqueConstraint("source", "source_policy_id", name="uq_policy_master_source_policy"),)

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source_policy_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    category_large: Mapped[str | None] = mapped_column(String(200), index=True)
    category_medium: Mapped[str | None] = mapped_column(String(200), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    managing_agency: Mapped[str | None] = mapped_column(String(255))
    operating_agency: Mapped[str | None] = mapped_column(String(255))
    contact_text: Mapped[str | None] = mapped_column(Text)
    support_cycle: Mapped[str | None] = mapped_column(String(100))
    provision_type: Mapped[str | None] = mapped_column(String(100))
    online_apply_yn: Mapped[bool | None] = mapped_column(Boolean)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    status_active_yn: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PolicyCondition(Base):
    __tablename__ = "policy_condition"

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    age_min: Mapped[int | None] = mapped_column(Integer)
    age_max: Mapped[int | None] = mapped_column(Integer)
    age_limit_yn: Mapped[bool | None] = mapped_column(Boolean)
    gender_male_yn: Mapped[bool | None] = mapped_column(Boolean)
    gender_female_yn: Mapped[bool | None] = mapped_column(Boolean)
    income_code: Mapped[str | None] = mapped_column(String(100))
    income_min_amount: Mapped[int | None] = mapped_column(Integer)
    income_max_amount: Mapped[int | None] = mapped_column(Integer)
    income_text: Mapped[str | None] = mapped_column(Text)
    household_type_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    employment_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    housing_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    life_cycle_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    school_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    major_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    marriage_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    region_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    special_target_codes_json: Mapped[list[str] | None] = mapped_column(JSON)
    additional_qualification_text: Mapped[str | None] = mapped_column(Text)
    restricted_target_text: Mapped[str | None] = mapped_column(Text)
    condition_source_confidence: Mapped[float | None] = mapped_column(Float)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PolicyBenefit(Base):
    __tablename__ = "policy_benefit"

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    benefit_detail_text: Mapped[str | None] = mapped_column(Text)
    benefit_amount_raw_text: Mapped[str | None] = mapped_column(Text)
    benefit_amount_value: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(10))
    benefit_period_label: Mapped[str | None] = mapped_column(String(200))
    support_scale_count: Mapped[int | None] = mapped_column(Integer)
    support_scale_limit_yn: Mapped[bool | None] = mapped_column(Boolean)
    first_come_first_served_yn: Mapped[bool | None] = mapped_column(Boolean)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PolicyApplication(Base):
    __tablename__ = "policy_application"

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    application_method_text: Mapped[str | None] = mapped_column(Text)
    application_period_text: Mapped[str | None] = mapped_column(Text)
    application_period_type_code: Mapped[str | None] = mapped_column(String(50))
    business_period_start_date: Mapped[str | None] = mapped_column(String(10))
    business_period_end_date: Mapped[str | None] = mapped_column(String(10))
    business_period_etc_text: Mapped[str | None] = mapped_column(Text)
    screening_method_text: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    online_apply_yn: Mapped[bool | None] = mapped_column(Boolean)
    receiving_org_name: Mapped[str | None] = mapped_column(String(255))
    processing_note_text: Mapped[str | None] = mapped_column(Text)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PolicyDocument(Base):
    __tablename__ = "policy_document"
    __table_args__ = (
        UniqueConstraint("policy_id", "document_group", "document_name", name="uq_policy_document_group_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_type: Mapped[str | None] = mapped_column(String(100), index=True)
    document_name: Mapped[str] = mapped_column(String(500), nullable=False)
    document_description: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    issued_within_days: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(String(30))
    document_group: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    file_url: Mapped[str | None] = mapped_column(Text)
    normalized_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class PolicyRelatedLink(Base):
    __tablename__ = "policy_related_link"
    __table_args__ = (
        UniqueConstraint("policy_id", "link_type", "link_url", name="uq_policy_related_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    link_name: Mapped[str | None] = mapped_column(String(500))
    link_url: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PolicyLaw(Base):
    __tablename__ = "policy_law"
    __table_args__ = (
        UniqueConstraint("policy_id", "law_name", name="uq_policy_law"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    law_name: Mapped[str] = mapped_column(String(500), nullable=False)
    law_type: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(30))


class PolicyTag(Base):
    __tablename__ = "policy_tag"
    __table_args__ = (
        UniqueConstraint("policy_id", "tag_type", "tag_code", name="uq_policy_tag"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tag_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tag_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tag_label: Mapped[str] = mapped_column(String(255), nullable=False)


class AnalysisProfileState(Base):
    __tablename__ = "analysis_profile_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    region_code: Mapped[str] = mapped_column(String(50), nullable=False)
    region_name: Mapped[str] = mapped_column(String(255), nullable=False)
    income_band: Mapped[str] = mapped_column(String(50), nullable=False)
    household_type: Mapped[str] = mapped_column(String(50), nullable=False)
    employment_status: Mapped[str] = mapped_column(String(50), nullable=False)
    housing_status: Mapped[str] = mapped_column(String(50), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AnalysisResultState(Base):
    __tablename__ = "analysis_result_state"

    policy_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False)
    score_level: Mapped[str] = mapped_column(String(20), nullable=False)
    apply_status: Mapped[str] = mapped_column(String(30), nullable=False)
    eligibility_summary: Mapped[str | None] = mapped_column(Text)
    blocking_reasons_json: Mapped[list[str] | None] = mapped_column(JSON)
    recommended_actions_json: Mapped[list[str] | None] = mapped_column(JSON)
    benefit_amount: Mapped[int | None] = mapped_column(Integer)
    benefit_amount_label: Mapped[str | None] = mapped_column(String(100))
    benefit_summary: Mapped[str | None] = mapped_column(String(255))
    badge_items_json: Mapped[list[str] | None] = mapped_column(JSON)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ApplicationDocumentState(Base):
    __tablename__ = "application_document_state"
    __table_args__ = (
        UniqueConstraint("policy_id", "document_type", name="uq_application_document_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    document_name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="MISSING")
    description: Mapped[str | None] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    issued_within_days: Mapped[int | None] = mapped_column(Integer)
    uploaded_file_url: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class ApplicationChecklistState(Base):
    __tablename__ = "application_checklist_state"
    __table_args__ = (
        UniqueConstraint("policy_id", "code", name="uq_application_checklist_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CommunityPost(Base):
    __tablename__ = "community_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String(100), nullable=False, default="남정현")
    author_masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    region_text: Mapped[str | None] = mapped_column(String(255))
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CommunityPostLike(Base):
    __tablename__ = "community_post_like"
    __table_args__ = (
        UniqueConstraint("post_id", "actor_key", name="uq_community_post_like"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    actor_key: Mapped[str] = mapped_column(String(100), nullable=False, default="demo-user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
