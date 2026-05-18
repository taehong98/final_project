from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisProfileState,
    AnalysisResultState,
    PolicyApplication,
    PolicyBenefit,
    PolicyCondition,
    PolicyDocument,
    PolicyMaster,
)
from app.schemas.common import ApplyStatus, ScoreLevel
from app.schemas.eligibility import AnalyzeRequest


@dataclass
class AnalyzedPolicy:
    policy_id: str
    title: str
    description: str | None
    match_score: int
    score_level: ScoreLevel
    apply_status: ApplyStatus
    eligibility_summary: str
    blocking_reasons: list[str]
    recommended_actions: list[str]
    benefit_amount: int | None
    benefit_amount_label: str | None
    benefit_summary: str | None
    badge_items: list[str]


INCOME_ORDER = {
    "MID_0_50": 1,
    "MID_50_60": 1,
    "MID_51_75": 2,
    "MID_60_80": 2,
    "MID_76_100": 3,
    "MID_80_100": 3,
    "MID_101_200": 4,
    "MID_200_PLUS": 5,
}

REGION_KEYWORDS: dict[str, set[str]] = {
    "서울": {"서울", "서울시", "서울특별시"},
    "부산": {"부산", "부산시", "부산광역시"},
    "대구": {"대구", "대구시", "대구광역시"},
    "인천": {"인천", "인천시", "인천광역시"},
    "광주": {"광주", "광주시", "광주광역시"},
    "대전": {"대전", "대전시", "대전광역시"},
    "울산": {"울산", "울산시", "울산광역시"},
    "세종": {"세종", "세종시", "세종특별자치시"},
    "경기": {"경기", "경기도", "수원", "용인", "성남", "안양", "고양", "부천", "화성", "평택", "포천"},
    "강원": {"강원", "강원도", "강원특별자치도"},
    "충북": {"충북", "충청북도"},
    "충남": {"충남", "충청남도"},
    "전북": {"전북", "전라북도", "전북특별자치도"},
    "전남": {"전남", "전라남도", "영암", "해남", "강진", "화순"},
    "경북": {"경북", "경상북도"},
    "경남": {"경남", "경상남도"},
    "제주": {"제주", "제주도", "제주특별자치도"},
}

NATIONAL_POLICY_KEYWORDS = {
    "전국", "전국민", "정부", "국가", "중앙", "부처", "공사", "공단", "재단",
    "고용노동부", "국토교통부", "보건복지부", "교육부", "금융위원회", "중소벤처기업부",
    "한국", "주택금융공사", "한국장학재단",
}

TARGET_MISMATCH_KEYWORDS = {
    "senior": {"노인", "어르신", "기초연금"},
    "youth": {"청년"},
    "family": {"신혼부부", "다자녀", "출산", "보육", "아동", "자녀", "육아", "한부모"},
    "self_employed": {"소상공인", "자영업", "창업자"},
    "employee_only": {"재직자", "근로자", "직장인", "고용보험"},
}


def _clamp_score(value: float | int) -> int:
    return max(0, min(99, int(round(value))))


def _score_level(score: int) -> ScoreLevel:
    if score >= 90:
        return ScoreLevel.HIGH
    if score >= 70:
        return ScoreLevel.MID
    return ScoreLevel.LOW


def _apply_status(score: int, blocking_reasons: list[str]) -> ApplyStatus:
    if blocking_reasons:
        return ApplyStatus.NOT_RECOMMENDED
    if score >= 90:
        return ApplyStatus.APPLICABLE_NOW
    if score < 45:
        return ApplyStatus.NOT_RECOMMENDED
    return ApplyStatus.NEEDS_CHECK


def _benefit_label(amount: int | None) -> str | None:
    if not amount:
        return None
    if amount >= 10000 and amount % 10000 == 0:
        return f"최대 {amount // 10000:,}만원"
    return f"최대 {amount:,}원"


def _normalize_title(title: str | None) -> str:
    if not title:
        return ""
    normalized = re.sub(r"\s+", " ", title).strip().lower()
    normalized = re.sub(r"\(.*?\)", "", normalized).strip()
    return normalized


def _dedupe_key(master: PolicyMaster) -> tuple[str, str]:
    return master.source, _normalize_title(master.title)


def _candidate_richness(
    master: PolicyMaster,
    benefit: PolicyBenefit | None,
    application: PolicyApplication | None,
) -> tuple[int, int, int, int]:
    return (
        1 if benefit and benefit.benefit_amount_value else 0,
        1 if application and application.application_url else 0,
        len(master.summary or ""),
        len(master.description or ""),
    )


def _policy_text_blob(
    master: PolicyMaster,
    condition: PolicyCondition | None,
    benefit: PolicyBenefit | None,
    application: PolicyApplication | None,
) -> str:
    parts = [
        master.title or "",
        master.summary or "",
        master.description or "",
        master.managing_agency or "",
        master.category_large or "",
        master.category_medium or "",
        (condition.additional_qualification_text if condition else "") or "",
        (condition.restricted_target_text if condition else "") or "",
        (benefit.benefit_detail_text if benefit else "") or "",
        (benefit.benefit_amount_raw_text if benefit else "") or "",
        (application.application_method_text if application else "") or "",
        (application.application_period_text if application else "") or "",
    ]
    return " ".join(str(part or "") for part in parts if part is not None).lower()


def _region_bucket(region_name: str | None) -> str | None:
    text = (region_name or "").strip()
    for bucket, keywords in REGION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return bucket
    return None


def cap_policy_score(
    *,
    req: AnalyzeRequest,
    master: PolicyMaster,
    condition: PolicyCondition | None,
    benefit: PolicyBenefit | None,
    application: PolicyApplication | None,
    score: int,
    blocking_reasons: list[str],
) -> int:
    policy_text = _policy_text_blob(master, condition, benefit, application)
    cap = 99

    if blocking_reasons:
        cap = min(cap, 44)

    request_region = _region_bucket(req.region_name)
    if request_region and not any(keyword in policy_text for keyword in NATIONAL_POLICY_KEYWORDS):
        request_keywords = REGION_KEYWORDS.get(request_region, set())
        matched_request_region = any(keyword.lower() in policy_text for keyword in request_keywords)
        other_region_hit = any(
            bucket != request_region and any(keyword.lower() in policy_text for keyword in keywords)
            for bucket, keywords in REGION_KEYWORDS.items()
        )
        if other_region_hit and not matched_request_region:
            cap = min(cap, 68)

    if req.age < 60 and any(keyword in policy_text for keyword in TARGET_MISMATCH_KEYWORDS["senior"]):
        cap = min(cap, 58)
    if req.age > 39 and any(keyword in policy_text for keyword in TARGET_MISMATCH_KEYWORDS["youth"]):
        cap = min(cap, 72)

    if req.household_type.value == "SINGLE" and any(
        keyword in policy_text for keyword in TARGET_MISMATCH_KEYWORDS["family"]
    ):
        cap = min(cap, 55)

    if req.employment_status.value != "SELF_EMPLOYED" and any(
        keyword in policy_text for keyword in TARGET_MISMATCH_KEYWORDS["self_employed"]
    ):
        cap = min(cap, 60)

    if req.employment_status.value == "UNEMPLOYED" and any(
        keyword in policy_text for keyword in TARGET_MISMATCH_KEYWORDS["employee_only"]
    ):
        cap = min(cap, 65)

    if req.housing_status.value == "MONTHLY_RENT":
        housing_terms = {"월세", "주거", "임대", "임차", "보증금", "전세"}
        if not any(term in policy_text for term in housing_terms):
            cap = min(cap, 78)

    if score >= 90 and cap == 99:
        cap = 95

    return min(score, cap)


def _condition_matches(
    req: AnalyzeRequest,
    condition: PolicyCondition | None,
    application: PolicyApplication | None,
) -> tuple[int, list[str], list[str], list[str]]:
    score = 70
    blocking_reasons: list[str] = []
    actions: list[str] = []
    tags: list[str] = []

    if not condition:
        return 60, blocking_reasons, actions, tags

    if condition.age_min is not None and req.age < condition.age_min:
        blocking_reasons.append(f"최소 연령 {condition.age_min}세 이상 조건이 필요합니다.")
    if condition.age_max is not None and req.age > condition.age_max:
        blocking_reasons.append(f"최대 연령 {condition.age_max}세 이하 조건이 필요합니다.")

    income_codes = set(condition.income_code.split(",")) if condition.income_code else set()
    if income_codes:
        req_level = INCOME_ORDER.get(req.income_band.value, 99)
        allowed = min(INCOME_ORDER.get(code, 99) for code in income_codes)
        if req_level > allowed:
            blocking_reasons.append("소득 구간 조건을 다시 확인해야 합니다.")
            actions.append("소득 기준과 공제 항목을 다시 확인해보세요.")
        else:
            score += 8

    employment_codes = set(condition.employment_codes_json or [])
    if employment_codes:
        if req.employment_status.value not in employment_codes:
            score -= 8
            actions.append("고용 상태 조건을 다시 확인해보세요.")
        else:
            score += 6

    household_codes = set(condition.household_type_codes_json or [])
    if household_codes:
        if req.household_type.value in household_codes:
            score += 6
            tags.append("가구 조건 충족")
        elif "SINGLE" in household_codes and req.household_type.value != "SINGLE":
            blocking_reasons.append("1인 가구 조건이 필요한 정책입니다.")

    if req.housing_status.value == "MONTHLY_RENT":
        score += 4
        tags.append("주거 조건 반영")

    if application and application.online_apply_yn:
        tags.append("온라인 신청")

    score = max(5, min(99, score))
    return score, blocking_reasons, actions, tags


def analyze_policies(db: Session, req: AnalyzeRequest) -> list[AnalyzedPolicy]:
    policy_rows = db.execute(
        select(PolicyMaster, PolicyCondition, PolicyBenefit, PolicyApplication)
        .outerjoin(PolicyCondition, PolicyCondition.policy_id == PolicyMaster.policy_id)
        .outerjoin(PolicyBenefit, PolicyBenefit.policy_id == PolicyMaster.policy_id)
        .outerjoin(PolicyApplication, PolicyApplication.policy_id == PolicyMaster.policy_id)
        .where(PolicyMaster.status_active_yn.is_(True))
        .order_by(PolicyMaster.policy_id)
    ).all()

    deduped: dict[tuple[str, str], tuple[AnalyzedPolicy, tuple[int, int, int, int]]] = {}

    for master, condition, benefit, application in policy_rows:
        score, blocking_reasons, actions, tags = _condition_matches(req, condition, application)
        score = cap_policy_score(
            req=req,
            master=master,
            condition=condition,
            benefit=benefit,
            application=application,
            score=score,
            blocking_reasons=blocking_reasons,
        )
        level = _score_level(score)
        apply_status = _apply_status(score, blocking_reasons)

        if apply_status == ApplyStatus.APPLICABLE_NOW:
            eligibility_summary = "현재 입력 조건 기준 신청 가능성이 높습니다."
        elif apply_status == ApplyStatus.NEEDS_CHECK:
            eligibility_summary = "일부 조건 확인이 필요하지만 신청 가능성이 있습니다."
        else:
            eligibility_summary = "현재 입력 조건 기준으로는 신청 가능성이 낮습니다."

        recommendation_actions = actions[:]
        if application and application.application_method_text:
            recommendation_actions.append("신청 방법과 접수 기관을 먼저 확인하세요.")
        if not recommendation_actions:
            recommendation_actions.append("현재 지역과 신청 요건을 다시 확인해보세요.")

        badge_items = [tag for tag in tags]
        badge_items.append(master.source.upper())
        if benefit and benefit.benefit_amount_value:
            benefit_label = _benefit_label(benefit.benefit_amount_value)
            if benefit_label:
                badge_items.append(benefit_label)
        badge_items = [item for item in badge_items if item][:3]

        candidate = AnalyzedPolicy(
            policy_id=master.policy_id,
            title=master.title,
            description=master.summary or master.description,
            match_score=score,
            score_level=level,
            apply_status=apply_status,
            eligibility_summary=eligibility_summary,
            blocking_reasons=blocking_reasons,
            recommended_actions=recommendation_actions[:4],
            benefit_amount=benefit.benefit_amount_value if benefit else None,
            benefit_amount_label=_benefit_label(benefit.benefit_amount_value if benefit else None),
            benefit_summary=benefit.benefit_period_label if benefit else None,
            badge_items=badge_items,
        )

        dedupe_key = _dedupe_key(master)
        richness = _candidate_richness(master, benefit, application)
        current = deduped.get(dedupe_key)

        if current is None:
            deduped[dedupe_key] = (candidate, richness)
            continue

        current_policy, current_richness = current
        candidate_rank = (
            candidate.apply_status == ApplyStatus.APPLICABLE_NOW,
            candidate.apply_status != ApplyStatus.NOT_RECOMMENDED,
            candidate.match_score,
            richness,
        )
        current_rank = (
            current_policy.apply_status == ApplyStatus.APPLICABLE_NOW,
            current_policy.apply_status != ApplyStatus.NOT_RECOMMENDED,
            current_policy.match_score,
            current_richness,
        )
        if candidate_rank > current_rank:
            deduped[dedupe_key] = (candidate, richness)

    results = [item[0] for item in deduped.values()]
    results.sort(
        key=lambda item: (
            item.apply_status != ApplyStatus.APPLICABLE_NOW,
            item.apply_status == ApplyStatus.NOT_RECOMMENDED,
            -item.match_score,
            item.title,
        )
    )
    return results


def persist_analysis_state(db: Session, req: AnalyzeRequest, analyzed: list[AnalyzedPolicy]) -> None:
    db.merge(
        AnalysisProfileState(
            id=1,
            age=req.age,
            region_code=req.region_code,
            region_name=req.region_name,
            income_band=req.income_band.value,
            household_type=req.household_type.value,
            employment_status=req.employment_status.value,
            housing_status=req.housing_status.value,
            updated_at=datetime.utcnow(),
        )
    )
    db.execute(delete(AnalysisResultState))

    for index, item in enumerate(analyzed, start=1):
        db.merge(
            AnalysisResultState(
                policy_id=item.policy_id,
                title=item.title,
                description=item.description,
                match_score=item.match_score,
                score_level=item.score_level.value,
                apply_status=item.apply_status.value,
                eligibility_summary=item.eligibility_summary,
                blocking_reasons_json=item.blocking_reasons,
                recommended_actions_json=item.recommended_actions,
                benefit_amount=item.benefit_amount,
                benefit_amount_label=item.benefit_amount_label,
                benefit_summary=item.benefit_summary,
                badge_items_json=item.badge_items,
                sort_order=index,
                updated_at=datetime.utcnow(),
            )
        )
    db.commit()


def get_profile_tags(req: AnalyzeRequest) -> list[str]:
    tags: list[str] = []
    if 19 <= req.age <= 34:
        tags.append("청년")
    if req.household_type.value == "SINGLE":
        tags.append("1인 가구")
    if req.employment_status.value == "UNEMPLOYED":
        tags.append("구직중")
    if req.housing_status.value == "MONTHLY_RENT":
        tags.append("월세")
    return tags[:3]


def get_analysis_results(db: Session) -> list[AnalysisResultState]:
    return db.execute(select(AnalysisResultState).order_by(AnalysisResultState.sort_order)).scalars().all()


def get_policy_documents(db: Session, policy_id: str) -> list[PolicyDocument]:
    return (
        db.execute(select(PolicyDocument).where(PolicyDocument.policy_id == policy_id).order_by(PolicyDocument.id))
        .scalars()
        .all()
    )


def score_level_from_score(score: int) -> ScoreLevel:
    return _score_level(score)


def apply_status_from_score(score: int, blocking_reasons: list[str]) -> ApplyStatus:
    return _apply_status(score, blocking_reasons)
