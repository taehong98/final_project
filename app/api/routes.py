from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
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
    PolicyTagItem,
    PolicySummary,
    RequiredDocumentItem,
    ScoreLevel,
    SuccessResponse,
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
from app.services.analysis import analyze_policies, get_analysis_results, get_policy_documents, get_profile_tags, persist_analysis_state
from app.services.application import ensure_application_state, get_application_step, update_checklist_state, update_document_state
from app.services.community import create_post, get_hot_posts, get_post, get_stats, like_post, list_posts, unlike_post


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
    return [
        PolicyLawItem(
            law_name=row.law_name,
            law_type=row.law_type,
            source=row.source,
        )
        for row in rows
    ]


def load_policy_tags(db: Session, policy_id: str, *, limit: int | None = None) -> list[PolicyTagItem]:
    stmt = select(PolicyTag).where(PolicyTag.policy_id == policy_id).order_by(PolicyTag.tag_type, PolicyTag.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [
        PolicyTagItem(
            tag_type=row.tag_type,
            tag_code=row.tag_code,
            tag_label=row.tag_label,
        )
        for row in rows
    ]


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
        level = ScoreLevel.HIGH
    elif match_score >= 65:
        level = ScoreLevel.MID
    else:
        level = ScoreLevel.LOW
    return PolicySummary(
        policy_id=policy_id,
        title=title,
        description=description,
        match_score=match_score,
        score_level=level,
        apply_status=apply_status,
        benefit_amount=benefit_amount,
        benefit_amount_label=benefit_amount_label,
        benefit_summary=benefit_summary,
        badge_items=badge_items,
        sort_order=sort_order,
    )


@router.post("/eligibility/analyze", response_model=SuccessResponse[AnalyzeResponseData])
def analyze(request: AnalyzeRequest, db: Session = Depends(get_db)):
    analyzed = analyze_policies(db, request)
    persist_analysis_state(db, request, analyzed)
    policies = [
        build_policy_summary(
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
        for index, item in enumerate(analyzed[:5], start=1)
    ]
    analysis_score = round(sum(item.match_score for item in analyzed[:5]) / max(1, len(analyzed[:5])))
    return SuccessResponse(
        data=AnalyzeResponseData(
            profile_summary=ProfileSummary(
                analysis_score=analysis_score,
                tags=get_profile_tags(request),
            ),
            policies=policies,
        )
    )


@router.get("/policies/search", response_model=SuccessResponse[PolicySearchData])
def search_policies(
    q: str = Query(..., min_length=1),
    size: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    keyword = q.strip()
    stmt = (
        select(PolicyMaster, PolicyBenefit, PolicyApplication, AnalysisResultState)
        .outerjoin(PolicyBenefit, PolicyBenefit.policy_id == PolicyMaster.policy_id)
        .outerjoin(PolicyApplication, PolicyApplication.policy_id == PolicyMaster.policy_id)
        .outerjoin(AnalysisResultState, AnalysisResultState.policy_id == PolicyMaster.policy_id)
        .where(PolicyMaster.status_active_yn.is_(True))
        .where(
            or_(
                PolicyMaster.title.ilike(f"%{keyword}%"),
                PolicyMaster.summary.ilike(f"%{keyword}%"),
                PolicyMaster.description.ilike(f"%{keyword}%"),
            )
        )
        .order_by(PolicyMaster.title.asc())
        .limit(size)
    )
    rows = db.execute(stmt).all()
    items: list[PolicySummary] = []
    for index, (master, benefit, application, analysis_result) in enumerate(rows, start=1):
        badge_items = [master.source.upper()]
        if master.managing_agency:
            badge_items.append(master.managing_agency)
        if benefit and benefit.benefit_amount_value:
            badge_items.append(f"최대 {benefit.benefit_amount_value:,}원")
        items.append(
            build_policy_summary(
                policy_id=master.policy_id,
                title=master.title,
                description=master.summary or master.description,
                match_score=analysis_result.match_score if analysis_result else 60,
                apply_status=ApplyStatus(analysis_result.apply_status) if analysis_result else ApplyStatus.NEEDS_CHECK,
                benefit_amount=benefit.benefit_amount_value if benefit else None,
                benefit_amount_label=analysis_result.benefit_amount_label if analysis_result else None,
                benefit_summary=(benefit.benefit_period_label if benefit else None),
                badge_items=badge_items[:3],
                sort_order=index,
            )
        )
    return SuccessResponse(data=PolicySearchData(items=items, query=keyword, total_count=len(items)))


@router.get("/policies/{policy_id}/detail", response_model=SuccessResponse[PolicyDetailData])
def get_policy_detail(policy_id: str, db: Session = Depends(get_db)):
    result = db.execute(select(AnalysisResultState).where(AnalysisResultState.policy_id == policy_id)).scalar_one_or_none()
    master = db.execute(select(PolicyMaster).where(PolicyMaster.policy_id == policy_id)).scalar_one_or_none()
    application = db.execute(select(PolicyApplication).where(PolicyApplication.policy_id == policy_id)).scalar_one_or_none()
    if not master:
        raise HTTPException(status_code=404, detail="Policy not found")
    if not result:
        raise HTTPException(status_code=404, detail="Analyze this policy first")

    documents = [
        RequiredDocumentItem(
            document_type=doc.document_type or f"DOC_{doc.id}",
            document_name=doc.document_name,
            is_required=doc.is_required,
            description=doc.document_description,
        )
        for doc in get_policy_documents(db, policy_id)
    ]
    related_links = load_policy_links(db, policy_id)
    laws = load_policy_laws(db, policy_id)
    tags = load_policy_tags(db, policy_id, limit=20)
    return SuccessResponse(
        data=PolicyDetailData(
            policy_id=master.policy_id,
            title=master.title,
            description=result.description,
            match_score=result.match_score,
            score_level=result.score_level,
            apply_status=result.apply_status,
            eligibility_summary=result.eligibility_summary,
            blocking_reasons=result.blocking_reasons_json or [],
            recommended_actions=result.recommended_actions_json or [],
            required_documents=documents,
            related_links=related_links,
            laws=laws,
            tags=tags,
            application_url=application.application_url if application else master.application_url,
            managing_agency=master.managing_agency,
            last_updated_at=master.updated_at,
        )
    )


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
                apply_status=row.apply_status,
                source=master.source if master else None,
                managing_agency=master.managing_agency if master else None,
                benefit_summary=row.benefit_summary,
                application_url=application.application_url if application else (master.application_url if master else None),
                tags=load_policy_tags(db, row.policy_id, limit=6),
                sort_order=row.sort_order,
            )
        )
    total = sum(item.amount or 0 for item in items)
    applicable_now_count = sum(1 for item in items if item.apply_status == ApplyStatus.APPLICABLE_NOW)
    needs_check_count = sum(1 for item in items if item.apply_status == ApplyStatus.NEEDS_CHECK)
    total_label = f"{total // 10000:,}만원" if total >= 10000 else f"{total:,}원"
    return SuccessResponse(
        data=PortfolioData(
            total_estimated_benefit_amount=total,
            total_estimated_benefit_label=total_label,
            selected_policy_count=len(items),
            applicable_now_count=applicable_now_count,
            needs_check_count=needs_check_count,
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
    related_links = load_policy_links(db, policy_id)
    laws = load_policy_laws(db, policy_id)
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
                ChecklistItem(
                    code=item.code,
                    label=item.label,
                    is_done=item.is_done,
                    sort_order=item.sort_order,
                )
                for item in checklist
            ],
            related_links=related_links,
            laws=laws,
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
    item = create_post(db, request.category, request.title, request.content, request.region_text)
    return SuccessResponse(data=CommunityPostItem(**item))


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
    items = get_hot_posts(db)
    return SuccessResponse(data=[CommunityPostItem(**item) for item in items])


@router.get("/community/stats", response_model=SuccessResponse[CommunityStatsData])
def community_stats(db: Session = Depends(get_db)):
    return SuccessResponse(data=CommunityStatsData(**get_stats(db)))
