from __future__ import annotations

import re
from typing import Any


def _make_slug(name: str, idx: int = 0) -> str:
    slug = re.sub(r"[^\w가-힣]", "-", str(name)).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    return slug or f"policy-{idx}"


def _score_to_css(score: int) -> dict:
    if score >= 80:
        return {
            "card_class": "top",
            "percent_class": "high",
            "progress_color": "green",
            "icon_color": "green",
            "badge_class": "badge-green",
            "badge_label": "✅ 조건 충족",
        }
    if score >= 60:
        return {
            "card_class": "mid",
            "percent_class": "mid",
            "progress_color": "blue",
            "icon_color": "blue",
            "badge_class": "badge-blue",
            "badge_label": "⚡ 확인 필요",
        }
    return {
        "card_class": "low",
        "percent_class": "low",
        "progress_color": "orange",
        "icon_color": "orange",
        "badge_class": "badge-orange",
        "badge_label": "⚠️ 조건 부족",
    }


def _pick_icon(policy: dict[str, Any]) -> str:
    text = " ".join([
        str(policy.get("서비스분야") or ""),
        str(policy.get("지원유형") or ""),
        str(policy.get("서비스명") or policy.get("policy_name") or ""),
    ])
    icon_map = {
        "주거": "🏠",
        "월세": "🏠",
        "전세": "🏠",
        "취업": "💼",
        "고용": "💼",
        "교육": "🎓",
        "장학": "🎓",
        "의료": "🏥",
        "건강": "🏥",
        "보육": "👶",
        "돌봄": "👶",
        "금융": "🏦",
        "대출": "🏦",
        "현금": "💰",
        "수당": "💰",
    }
    for key, icon in icon_map.items():
        if key in text:
            return icon
    return "📋"


def _extract_benefit(policy: dict[str, Any]) -> str:
    text = str(policy.get("지원내용") or policy.get("서비스목적요약") or policy.get("evidence_text") or "").strip()

    m = re.search(r"월\s*([\d,]+)\s*만\s*원?\s*[×x]\s*최대\s*(\d+)\s*개월", text)
    if m:
        return f"최대 {int(m.group(1).replace(',', '')) * int(m.group(2)):,}만원"

    candidates = re.findall(r"(최대|월|연|1인당|가구당)?\s*([\d,]+)\s*만\s*원", text)
    if candidates:
        best_val, best_str = 0, ""
        for prefix, num_str in candidates:
            val = int(num_str.replace(",", ""))
            if val > best_val:
                best_val = val
                best_str = f"{prefix.strip()} {val:,}만원".strip() if prefix.strip() else f"{val:,}만원"
        if best_str:
            return re.sub(r"만\s+원", "만원", best_str)

    amounts = re.findall(r"([\d,]+)\s*원", text)
    if amounts:
        try:
            max_val = max(int(a.replace(",", "")) for a in amounts)
            return f"최대 {max_val // 10000:,}만원" if max_val >= 10000 else f"최대 {max_val:,}원"
        except Exception:
            pass

    return policy.get("지원유형") or "지원내용 확인"


def _make_subtitle(policy: dict[str, Any]) -> str:
    target = str(policy.get("지원대상") or "").strip()
    criteria = str(policy.get("선정기준") or "").strip()
    org = str(policy.get("소관기관명") or "").strip()
    parts = []
    if target:
        parts.append(target[:20])
    if criteria:
        parts.append(criteria[:20])
    elif org:
        parts.append(org[:20])
    return " · ".join(parts[:2]) if parts else "세부 조건 확인 필요"


def _split_sentences(text: str) -> list[str]:
    text = str(text or "").replace("\n", " ")
    parts = re.split(r"(?<=[.!?])\s+|[;；]", text)
    return [p.strip() for p in parts if p and p.strip()]


def _clean_field(text: str) -> str:
    text = str(text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _build_summary(policy: dict[str, Any], score_pct: int) -> str:
    name = str(policy.get("서비스명") or policy.get("policy_name") or "정책")
    target = _clean_field(policy.get("지원대상") or "")
    content = _clean_field(policy.get("지원내용") or "")
    deadline = _clean_field(policy.get("신청기한") or "")

    sentences: list[str] = []
    if target:
        sentences.append(f"{name}은(는) {target} 대상 정책입니다.")
    else:
        sentences.append(f"{name} 정책입니다.")

    if content:
        sentences.append(f"지원 내용은 {content}입니다.")

    if deadline and deadline != "상시신청":
        sentences.append(f"신청기한은 {deadline}입니다.")

    if score_pct < 60:
        sentences.append("현재 입력 조건으로는 바로 신청 가능성이 낮아 세부 자격을 다시 확인하는 것이 좋습니다.")
    elif score_pct < 80:
        sentences.append("기본 조건은 대체로 맞지만 일부 확인이 더 필요합니다.")
    else:
        sentences.append("현재 입력 조건 기준으로 우선 검토해볼 만한 정책입니다.")

    return " ".join(sentences[:4]).strip()


def _build_reason_items(policy: dict[str, Any], score_pct: int) -> list[dict[str, str]]:
    failed = list(policy.get("failed") or [])
    soft_failed = list(policy.get("soft_failed") or [])

    reasons = failed or soft_failed
    if not reasons:
        reasons = ["정책 기준상 뚜렷한 탈락 사유는 확인되지 않았습니다."]

    items = []
    for reason in reasons[:3]:
        items.append({
            "icon": "⚠️" if "없습니다" not in reason else "✅",
            "html": f"<strong>핵심 사유:</strong> {reason}",
        })
    return items


def _build_guide_items(policy: dict[str, Any], reason_items: list[dict[str, str]]) -> list[dict[str, str]]:
    guides: list[dict[str, str]] = []

    target = _clean_field(policy.get("지원대상") or "")
    deadline = _clean_field(policy.get("신청기한") or "")
    method = _clean_field(policy.get("신청방법") or "")

    first_reason = reason_items[0]["html"] if reason_items else ""
    reason_text = re.sub(r"<[^>]+>", "", first_reason)

    if "지역 조건 불일치" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 거주지역 기준을 다시 확인하고, 해당 지자체 거주자 전용 정책인지 확인하세요."})
    elif "소득 조건 미충족" in reason_text or "소득 한도" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 소득 기준과 가구원 수 기준표를 공고문에서 다시 확인하세요."})
    elif "가구 조건 미충족" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 가구 유형 전용 정책인지 확인하고, 본인 가구 형태와 일치하는지 점검하세요."})
    elif "고용 상태 불일치" in reason_text:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 미취업·구직중·재직중 등 고용 상태 기준을 공고문에서 다시 확인하세요."})
    elif "정책 기준상 뚜렷한 탈락 사유" in reason_text:
        if target:
            guides.append({"icon": "✅", "html": f"<strong>1단계:</strong> 지원대상과 세부 자격을 다시 확인하세요: {target}"})
    else:
        guides.append({"icon": "✅", "html": "<strong>1단계:</strong> 공고문 원문에서 세부 자격 요건을 다시 확인하세요."})

    if deadline:
        guides.append({"icon": "📎", "html": f"<strong>2단계:</strong> 신청기한을 확인하세요: {deadline}"})
    if method:
        guides.append({"icon": "🚀", "html": f"<strong>3단계:</strong> 신청방법을 확인하세요: {method}"})

    return guides[:3]


def _dashboard_tags(user: dict) -> list[str]:
    return [
        f"📅 만 {user.get('나이', user.get('age', '-'))}세",
        f"📍 {user.get('거주지역', user.get('region', '-'))}",
        f"💰 중위소득 {user.get('income_percent', '-')}%",
        f"🏠 {user.get('가구유형', user.get('household_type', '-'))}",
        f"👔 {user.get('고용상태', user.get('employment_status', '-'))}",
    ]


def analyze(user: dict, policies: list[dict]) -> dict:
    portfolio = []
    total_score = 0

    for idx, policy in enumerate(policies[:10], start=1):
        policy_name = str(policy.get("서비스명") or policy.get("policy_name") or f"정책-{idx}")
        score_raw = policy.get("score", 0)
        try:
            score_pct = int(round(float(score_raw) * 100)) if float(score_raw) <= 1 else int(round(float(score_raw)))
        except Exception:
            score_pct = 0

        reason_items = _build_reason_items(policy, score_pct)
        guide_items = _build_guide_items(policy, reason_items)

        item = {
            "policy_id": _make_slug(policy_name, idx),
            "서비스명": policy_name,
            "icon": _pick_icon(policy),
            "subtitle": _make_subtitle(policy),
            "benefit_label": _extract_benefit(policy),
            "source_label": str(policy.get("소관기관명") or "복지 정책")[:8],
            "eligibility_percent": score_pct,
            "수급확률": score_pct,
            "개인요약": _build_summary(policy, score_pct),
            "탈락사유": reason_items,
            "해결방법": guide_items,
            "우선순위": idx,
            "중복수급주의": False,
            "_css": _score_to_css(score_pct),
            "_matched": policy.get("matched", []),
            "_failed": policy.get("failed", []),
            "_issues": reason_items,
            "_guides": guide_items,
            "_raw": policy,
        }
        portfolio.append(item)
        total_score += score_pct

    avg_score = round(total_score / len(portfolio)) if portfolio else 0
    immediate_count = sum(1 for x in portfolio if x.get("수급확률", 0) >= 80)

    return {
        "포트폴리오": portfolio,
        "종합요약": f"총 {len(portfolio)}개의 정책을 분석했습니다. 평균 수급 확률은 {avg_score}%이며, 즉시 신청 가능 수준의 정책은 {immediate_count}건입니다.",
        "대시보드통계": {
            "해당정책수": len(portfolio),
            "평균확률": avg_score,
            "예상수혜액": "정책별 지원내용 확인",
            "즉시신청가능": immediate_count,
        },
        "cards": portfolio,
        "dashboard_data": {
            "user_profile": {
                "user_name": str(user.get("user_name", user.get("이름", "사용자"))),
                "updated_at_label": "오늘",
                "region_label": str(user.get("거주지역", user.get("region", "-"))),
                "total_score": avg_score,
                "score_max": 100,
                "tags": _dashboard_tags(user),
            },
            "condition_form": {
                "current_values": {
                    "age_label": f"만 {user.get('나이', user.get('age', '-'))}세",
                    "region": str(user.get("거주지역", user.get("region", "-"))),
                    "income_label": f"중위소득 {user.get('income_percent', '-')}%",
                    "household_type": str(user.get("가구유형", user.get("household_type", "-"))),
                    "employment_status": str(user.get("고용상태", user.get("employment_status", "-"))),
                    "education_level": str(user.get("education_level", user.get("학력", ""))),
                }
            },
            "dashboard_stats": {
                "matched_policy_count": len(portfolio),
                "average_probability_percent": avg_score,
                "expected_total_benefit_label": "-",
                "ready_apply_count": immediate_count,
            },
            "stats": {
                "해당정책수": len(portfolio),
                "평균확률": avg_score,
                "예상수혜액": "정책별 지원내용 확인",
                "즉시신청가능": immediate_count,
            },
            "portfolio_preview": {
                "total_expected_benefit_label": "-",
                "items": [
                    {
                        "icon": item["icon"],
                        "label": item["서비스명"],
                        "benefit_label": item["benefit_label"],
                    }
                    for item in portfolio[:4]
                ],
            },
            "summary": f"총 {len(portfolio)}개 정책 분석 완료. 수급 가능(60% 이상) {sum(1 for x in portfolio if x.get('수급확률', 0) >= 60)}건.",
        },
    }
