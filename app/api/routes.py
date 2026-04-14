from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import AnalysisResultState, PolicyApplication, PolicyBenefit, PolicyLaw, PolicyMaster, PolicyRelatedLink, PolicyTag
from app.schemas.application import ApplicationPrepData, ChecklistPatchRequest, DocumentPatchRequest
from app.schemas.common import (
    ApplyStatus,
    ApplicationStep,
    ChecklistItem,
    DocumentStatus,
    PolicyLawItem,
    PolicyLinkItem,
    PolicySummary,
    PolicyTagItem,
    RequiredDocumentItem,
    ScoreLevel,
    SuccessResponse,
    UnmatchedPolicyItem,
)
from app.schemas.community import (
    CommunityCreateRequest,
    CommunityLikeData,
    CommunityListData,
    CommunityPostItem,
    CommunityStatsData,
)
from app.schemas.detail import PolicyDetailData
from app.schemas.eligibility import AnalyzeRequest, AnalyzeResponseData, ProfileSummary
from app.schemas.portfolio import PortfolioData, PortfolioItem
from app.schemas.search import PolicySearchData
from app.services.analysis import AnalyzedPolicy, get_analysis_results, get_policy_documents, get_profile_tags, persist_analysis_state
from app.services.application import ensure_application_state, get_application_step, update_checklist_state, update_document_state
from app.services.community import create_post, get_hot_posts, get_post, get_stats, like_post, list_posts, unlike_post
from app.services.rag import search_rag


router = APIRouter(prefix="/api/v1")


def load_policy_links(db: Session, policy_id: str) -> list[PolicyLinkItem]:
    rows = db.execute(
        select(PolicyRelatedLink)
        .where(PolicyRelatedLink.policy_id == policy_id)
        .order_by(PolicyRelatedLink.sort_order, PolicyRelatedLink.id)
    ).scalars().all()
    return [
        PolicyLinkItem(
            link_type=row.link_type,
            link_name=row.link_name,
            link_url=row.link_url,
            sort_order=row.sort_order,
        )
        for row in rows
    ]


def load_policy_laws(db: Session, policy_id: str) -> list[PolicyLawItem]:
    rows = db.execute(select(PolicyLaw).where(PolicyLaw.policy_id == policy_id).order_by(PolicyLaw.id)).scalars().all()
    return [PolicyLawItem(law_name=row.law_name, law_type=row.law_type, source=row.source) for row in rows]


def load_policy_tags(db: Session, policy_id: str, *, limit: int | None = None) -> list[PolicyTagItem]:
    stmt = select(PolicyTag).where(PolicyTag.policy_id == policy_id).order_by(PolicyTag.tag_type, PolicyTag.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [PolicyTagItem(tag_type=row.tag_type, tag_code=row.tag_code, tag_label=row.tag_label) for row in rows]


def build_policy_summary(
    *,
    policy_id: str,
    title: str,
    description: str | None,
    match_score: int,
    apply_status: ApplyStatus,
    benefit_amount: int | None,
    benefit_amount_label: str | None,
    benefit_summary: str | None,
    badge_items: list[str],
    sort_order: int,
) -> PolicySummary:
    if match_score >= 85:
        score_level = ScoreLevel.HIGH
    elif match_score >= 65:
        score_level = ScoreLevel.MID
    else:
        score_level = ScoreLevel.LOW

    return PolicySummary(
        policy_id=policy_id,
        title=title,
        description=description,
        match_score=match_score,
        score_level=score_level,
        apply_status=apply_status,
        benefit_amount=benefit_amount,
        benefit_amount_label=benefit_amount_label,
        benefit_summary=benefit_summary,
        badge_items=badge_items,
        sort_order=sort_order,
    )


def infer_source_from_reference(reference_id: str) -> str | None:
    if "__" in reference_id:
        return reference_id.split("__", 1)[0]
    normalized = reference_id.upper()
    if normalized.startswith("WLF"):
        return "bokjiro"
    if reference_id.isdigit():
        return "gov24"
    return None


def build_summary_from_master(
    db: Session,
    master: PolicyMaster,
    *,
    index: int,
    fallback_score: int = 60,
    use_analysis_state: bool = False,
) -> PolicySummary:
    benefit = db.execute(select(PolicyBenefit).where(PolicyBenefit.policy_id == master.policy_id)).scalar_one_or_none()
    application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == master.policy_id)).scalar_one_or_none()
    analysis_result = None
    if use_analysis_state:
        analysis_result = db.execute(select(AnalysisResultState).where(AnalysisResultState.policy_id == master.policy_id)).scalar_one_or_none()

    badge_items = [master.source.upper()]
    if master.managing_agency:
        badge_items.append(master.managing_agency)
    if application and application.online_apply_yn:
        badge_items.append("온라인 신청")
    if benefit and benefit.benefit_amount_value:
        if benefit.benefit_amount_value >= 10000:
            badge_items.append(f"최대 {benefit.benefit_amount_value // 10000:,}만원")
        else:
            badge_items.append(f"최대 {benefit.benefit_amount_value:,}원")

    return build_policy_summary(
        policy_id=master.policy_id,
        title=master.title,
        description=master.summary or master.description,
        match_score=analysis_result.match_score if analysis_result else fallback_score,
        apply_status=ApplyStatus(analysis_result.apply_status) if analysis_result else ApplyStatus.NEEDS_CHECK,
        benefit_amount=benefit.benefit_amount_value if benefit else None,
        benefit_amount_label=analysis_result.benefit_amount_label if analysis_result else None,
        benefit_summary=(analysis_result.benefit_summary if analysis_result else (benefit.benefit_period_label if benefit else None)),
        badge_items=badge_items[:3],
        sort_order=index,
    )


def build_analyzed_from_master(
    db: Session,
    master: PolicyMaster,
    *,
    index: int,
    rag_answer: str | None = None,
) -> AnalyzedPolicy:
    benefit = db.execute(select(PolicyBenefit).where(PolicyBenefit.policy_id == master.policy_id)).scalar_one_or_none()
    application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == master.policy_id)).scalar_one_or_none()

    score = max(70, 96 - ((index - 1) * 3))
    apply_status = ApplyStatus.APPLICABLE_NOW if (application and (application.online_apply_yn or application.application_url)) else ApplyStatus.NEEDS_CHECK
    score_level = ScoreLevel.HIGH if score >= 85 else ScoreLevel.MID

    badge_items = [master.source.upper()]
    if master.managing_agency:
        badge_items.append(master.managing_agency)
    if application and application.online_apply_yn:
        badge_items.append("온라인 신청")
    elif application and application.application_url:
        badge_items.append("신청 링크")
    if benefit and benefit.benefit_amount_value:
        if benefit.benefit_amount_value >= 10000:
            badge_items.append(f"최대 {benefit.benefit_amount_value // 10000:,}만원")
        else:
            badge_items.append(f"최대 {benefit.benefit_amount_value:,}원")

    eligibility_summary = rag_answer or "RAG 검색 결과 기준으로 현재 조건과 연관성이 높은 정책입니다."
    recommended_actions = ["정책 상세 정보를 확인한 뒤 신청 자격과 제출 서류를 점검해보세요."]
    if application and application.application_method_text:
        recommended_actions.append("신청 방법과 접수 기간을 먼저 확인해보세요.")

    return AnalyzedPolicy(
        policy_id=master.policy_id,
        title=master.title,
        description=master.summary or master.description,
        match_score=score,
        score_level=score_level,
        apply_status=apply_status,
        eligibility_summary=eligibility_summary,
        blocking_reasons=[],
        recommended_actions=recommended_actions[:4],
        benefit_amount=benefit.benefit_amount_value if benefit else None,
        benefit_amount_label=(f"최대 {benefit.benefit_amount_value // 10000:,}만원" if benefit and benefit.benefit_amount_value and benefit.benefit_amount_value >= 10000 else (f"최대 {benefit.benefit_amount_value:,}원" if benefit and benefit.benefit_amount_value else None)),
        benefit_summary=benefit.benefit_period_label if benefit else None,
        badge_items=badge_items[:3],
    )


def build_summary_from_analyzed(item: AnalyzedPolicy, *, index: int) -> PolicySummary:
    return build_policy_summary(
        policy_id=item.policy_id,
        title=item.title,
        description=item.description,
        match_score=item.match_score,
        apply_status=item.apply_status,
        benefit_amount=item.benefit_amount,
        benefit_amount_label=item.benefit_amount_label,
        benefit_summary=item.benefit_summary,
        badge_items=item.badge_items,
        sort_order=index,
    )


def resolve_rag_references(
    db: Session,
    references: list[str],
    *,
    rag_answer: str | None = None,
) -> tuple[list[PolicySummary], list[AnalyzedPolicy], list[UnmatchedPolicyItem]]:
    items: list[PolicySummary] = []
    matched_analyzed: list[AnalyzedPolicy] = []
    unmatched: list[UnmatchedPolicyItem] = []
    seen_policy_ids: set[str] = set()

    for index, reference_id in enumerate(references, start=1):
        master = None
        source = infer_source_from_reference(reference_id)

        if "__" in reference_id:
            master = db.execute(select(PolicyMaster).where(PolicyMaster.policy_id == reference_id)).scalar_one_or_none()

        if master is None:
            stmt = select(PolicyMaster).where(PolicyMaster.source_policy_id == reference_id)
            if source:
                stmt = stmt.where(PolicyMaster.source == source)
            master = db.execute(stmt.order_by(PolicyMaster.policy_id.asc())).scalar_one_or_none()

        if master is None:
            unmatched.append(UnmatchedPolicyItem(reference_id=reference_id, source=source))
            continue

        if master.policy_id in seen_policy_ids:
            continue

        analyzed_item = build_analyzed_from_master(db, master, index=index, rag_answer=rag_answer)
        items.append(build_summary_from_analyzed(analyzed_item, index=index))
        matched_analyzed.append(analyzed_item)
        seen_policy_ids.add(master.policy_id)

    return items, matched_analyzed, unmatched


def build_rag_condition_query(request: AnalyzeRequest) -> str:
    household_label = {
        "SINGLE": "1인 가구",
        "TWO_PERSON": "2인 가구",
        "MULTI_PERSON": "다인 가구",
    }[request.household_type.value]
    employment_label = {
        "UNEMPLOYED": "미취업",
        "EMPLOYED": "재직 중",
        "SELF_EMPLOYED": "자영업",
    }[request.employment_status.value]
    housing_label = {
        "MONTHLY_RENT": "월세",
        "JEONSE": "전세",
        "OWNER_FAMILY_HOME": "자가 또는 가족 소유 주택",
    }[request.housing_status.value]
    income_label = {
        "MID_50_60": "중위소득 50~60%",
        "MID_60_80": "중위소득 60~80%",
        "MID_80_100": "중위소득 80~100%",
    }[request.income_band.value]
    return f"{request.region_name} 거주, 만 {request.age}세, {household_label}, {employment_label}, {housing_label}, {income_label} 조건에 맞는 복지 정책"


def build_detail_data(db: Session, policy_id: str) -> PolicyDetailData:
    master = db.execute(select(PolicyMaster).where(PolicyMaster.policy_id == policy_id)).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Policy not found")

    application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == policy_id)).scalar_one_or_none()
    result = db.execute(select(AnalysisResultState).where(AnalysisResultState.policy_id == policy_id)).scalar_one_or_none()

    documents = [
        RequiredDocumentItem(
            document_type=doc.document_type or f"DOC_{doc.id}",
            document_name=doc.document_name,
            is_required=doc.is_required,
            description=doc.document_description,
        )
        for doc in get_policy_documents(db, policy_id)
    ]

    if result:
        description = result.description
        match_score = result.match_score
        score_level = ScoreLevel(result.score_level)
        apply_status = ApplyStatus(result.apply_status)
        eligibility_summary = result.eligibility_summary
        blocking_reasons = result.blocking_reasons_json or []
        recommended_actions = result.recommended_actions_json or []
    else:
        description = master.summary or master.description
        match_score = 60
        score_level = ScoreLevel.MID
        apply_status = ApplyStatus.NEEDS_CHECK
        eligibility_summary = "분석 결과가 아직 없어 정책 기본 정보 기준으로 보여주고 있습니다."
        blocking_reasons = []
        recommended_actions = ["AI 분석 실행 후 개인 조건 기준 상세 적합도를 다시 확인해보세요."]

    return PolicyDetailData(
        policy_id=master.policy_id,
        title=master.title,
        description=description,
        match_score=match_score,
        score_level=score_level,
        apply_status=apply_status,
        eligibility_summary=eligibility_summary,
        blocking_reasons=blocking_reasons,
        recommended_actions=recommended_actions,
        required_documents=documents,
        related_links=load_policy_links(db, policy_id),
        laws=load_policy_laws(db, policy_id),
        tags=load_policy_tags(db, policy_id, limit=20),
        application_url=application.application_url if application else master.application_url,
        managing_agency=master.managing_agency,
        last_updated_at=master.updated_at,
    )


@router.post("/eligibility/analyze", response_model=SuccessResponse[AnalyzeResponseData])
def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    rag_result = search_rag(
        query=build_rag_condition_query(request),
        user_condition={
            "age": request.age,
            "region": request.region_name,
            "income_band": request.income_band.value,
            "household_type": request.household_type.value,
            "employment_status": request.employment_status.value,
            "housing_status": request.housing_status.value,
        },
        lang_code="ko",
    )

    rag_policies, rag_analyzed, unmatched = resolve_rag_references(
        db,
        rag_result.docs_used,
        rag_answer=rag_result.answer,
    )
    persist_analysis_state(db, request, rag_analyzed)
    policies = rag_policies[:5]

    analysis_score = round(sum(item.match_score for item in policies) / max(1, len(policies)))
    return SuccessResponse(
        data=AnalyzeResponseData(
            profile_summary=ProfileSummary(analysis_score=analysis_score, tags=get_profile_tags(request)),
            policies=policies,
            rag_answer=rag_result.answer,
            rag_docs_used=rag_result.docs_used,
            unmatched_policies=unmatched,
        )
    )


@router.get("/policies/search", response_model=SuccessResponse[PolicySearchData])
def search_policies(
    q: str = Query(..., min_length=1),
    size: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    keyword = q.strip()
    rag_result = search_rag(query=keyword, user_condition={}, lang_code="ko")
    items, _, unmatched = resolve_rag_references(db, rag_result.docs_used[:size])

    return SuccessResponse(
        data=PolicySearchData(
            items=items[:size],
            query=keyword,
            total_count=len(items),
            rag_answer=rag_result.answer,
            rag_docs_used=rag_result.docs_used,
            unmatched_policies=unmatched,
        )
    )


@router.get("/policies/{policy_id}/detail", response_model=SuccessResponse[PolicyDetailData])
def get_policy_detail(policy_id: str, db: Session = Depends(get_db)):
    return SuccessResponse(data=build_detail_data(db, policy_id))


@router.get("/portfolio", response_model=SuccessResponse[PortfolioData])
def get_portfolio(db: Session = Depends(get_db)):
    results = get_analysis_results(db)
    if not results:
        raise HTTPException(status_code=404, detail="Run analyze first")

    items: list[PortfolioItem] = []
    for row in results[:5]:
        master = db.execute(select(PolicyMaster).where(PolicyMaster.policy_id == row.policy_id)).scalar_one_or_none()
        application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == row.policy_id)).scalar_one_or_none()
        items.append(
            PortfolioItem(
                policy_id=row.policy_id,
                title=row.title,
                amount=row.benefit_amount,
                amount_label=row.benefit_amount_label,
                period_label=row.benefit_summary,
                apply_status=ApplyStatus(row.apply_status),
                source=master.source if master else None,
                managing_agency=master.managing_agency if master else None,
                benefit_summary=row.benefit_summary,
                application_url=application.application_url if application else (master.application_url if master else None),
                tags=load_policy_tags(db, row.policy_id, limit=6),
                sort_order=row.sort_order,
            )
        )

    total = sum(item.amount or 0 for item in items)
    total_label = f"{total // 10000:,}만원" if total >= 10000 else f"{total:,}원"
    return SuccessResponse(
        data=PortfolioData(
            total_estimated_benefit_amount=total,
            total_estimated_benefit_label=total_label,
            selected_policy_count=len(items),
            applicable_now_count=sum(1 for item in items if item.apply_status == ApplyStatus.APPLICABLE_NOW),
            needs_check_count=sum(1 for item in items if item.apply_status == ApplyStatus.NEEDS_CHECK),
            portfolio_items=items,
        )
    )


@router.get("/applications/{policy_id}/prep", response_model=SuccessResponse[ApplicationPrepData])
def get_application_prep(policy_id: str, db: Session = Depends(get_db)):
    master = db.execute(select(PolicyMaster).where(PolicyMaster.policy_id == policy_id)).scalar_one_or_none()
    application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == policy_id)).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Policy not found")

    documents, checklist = ensure_application_state(db, policy_id)
    return SuccessResponse(
        data=ApplicationPrepData(
            policy_id=policy_id,
            application_step=ApplicationStep(get_application_step(db, policy_id)),
            required_documents=[
                RequiredDocumentItem(
                    document_type=item.document_type,
                    document_name=item.document_name,
                    status=DocumentStatus(item.status),
                    description=item.description,
                    is_required=item.is_required,
                    issued_within_days=item.issued_within_days,
                    uploaded_file_url=item.uploaded_file_url,
                    verified_at=item.verified_at,
                )
                for item in documents
            ],
            checklist_items=[
                ChecklistItem(code=item.code, label=item.label, is_done=item.is_done, sort_order=item.sort_order)
                for item in checklist
            ],
            related_links=load_policy_links(db, policy_id),
            laws=load_policy_laws(db, policy_id),
            application_url=application.application_url if application else master.application_url,
        )
    )


@router.patch("/applications/{policy_id}/checklist/{code}", response_model=SuccessResponse[ChecklistItem])
def patch_checklist(policy_id: str, code: str, request: ChecklistPatchRequest, db: Session = Depends(get_db)):
    item = update_checklist_state(db, policy_id, code, request.is_done)
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")
    return SuccessResponse(data=ChecklistItem(code=item.code, label=item.label, is_done=item.is_done, sort_order=item.sort_order))


@router.patch("/applications/{policy_id}/documents/{document_type}", response_model=SuccessResponse[RequiredDocumentItem])
def patch_document(policy_id: str, document_type: str, request: DocumentPatchRequest, db: Session = Depends(get_db)):
    item = update_document_state(db, policy_id, document_type, request.status.value, request.uploaded_file_url)
    if not item:
        raise HTTPException(status_code=404, detail="Document not found")
    return SuccessResponse(
        data=RequiredDocumentItem(
            document_type=item.document_type,
            document_name=item.document_name,
            status=DocumentStatus(item.status),
            description=item.description,
            is_required=item.is_required,
            issued_within_days=item.issued_within_days,
            uploaded_file_url=item.uploaded_file_url,
            verified_at=item.verified_at,
        )
    )


@router.get("/community/posts", response_model=SuccessResponse[CommunityListData])
def community_posts(
    category: str = Query(default="all"),
    sort: str = Query(default="latest"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    items, total_count = list_posts(db, category=category, sort=sort, page=page, size=size)
    return SuccessResponse(
        data=CommunityListData(
            items=[CommunityPostItem(**item) for item in items],
            page=page,
            size=size,
            total_count=total_count,
            has_next=(page * size) < total_count,
        )
    )


@router.get("/community/posts/{post_id}", response_model=SuccessResponse[CommunityPostItem])
def community_post_detail(post_id: int, db: Session = Depends(get_db)):
    item = get_post(db, post_id)
    if not item:
        raise HTTPException(status_code=404, detail="Post not found")
    return SuccessResponse(data=CommunityPostItem(**item))


@router.post("/community/posts", response_model=SuccessResponse[CommunityPostItem])
def community_post_create(request: CommunityCreateRequest, db: Session = Depends(get_db)):
    if request.category == "regional" and not request.region_text:
        raise HTTPException(status_code=400, detail="region_text is required for regional posts")
    return SuccessResponse(
        data=CommunityPostItem(**create_post(db, request.category, request.title, request.content, request.region_text))
    )


@router.post("/community/posts/{post_id}/like", response_model=SuccessResponse[CommunityLikeData])
def community_post_like(post_id: int, db: Session = Depends(get_db)):
    item = like_post(db, post_id)
    if not item:
        raise HTTPException(status_code=404, detail="Post not found")
    return SuccessResponse(data=CommunityLikeData(**item))


@router.delete("/community/posts/{post_id}/like", response_model=SuccessResponse[CommunityLikeData])
def community_post_unlike(post_id: int, db: Session = Depends(get_db)):
    item = unlike_post(db, post_id)
    if not item:
        raise HTTPException(status_code=404, detail="Post not found")
    return SuccessResponse(data=CommunityLikeData(**item))


@router.get("/community/hot-posts", response_model=SuccessResponse[list[CommunityPostItem]])
def community_hot_posts(db: Session = Depends(get_db)):
    return SuccessResponse(data=[CommunityPostItem(**item) for item in get_hot_posts(db)])


@router.get("/community/stats", response_model=SuccessResponse[CommunityStatsData])
def community_stats(db: Session = Depends(get_db)):
    return SuccessResponse(data=CommunityStatsData(**get_stats(db)))
