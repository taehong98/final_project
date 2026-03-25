"""
07 수급 가능성 스코어링
=======================
Rule-based + numpy 기반 정책별 수급 가능성 점수 계산

HTML 폼 6개 항목과 완전 일치하도록 가중치 재설계:
  연령(0.25) + 소득(0.25) + 가구유형(0.15) + 지역(0.10) + 고용상태(0.15) + 장애여부(0.10)
  = 1.00

변경 사항:
  - W_SPECIAL(0.05) 제거 → 장애여부(W_DISABILITY=0.10)로 독립 항목 승격
  - W_EMPLOYMENT 0.10 → 0.15 (고용상태 비중 상향)
  - W_AGE / W_INCOME 0.30 → 0.25 (장애여부 항목 신설로 분산)
  - 장애여부 조건 없는 정책 → 장애여부 가중치 전액 충족으로 간주
  - 국가유공자 / 다문화 조건은 고용상태 블록 내 보조 체크로 유지
"""

from __future__ import annotations

import re
import logging
import numpy as np

log = logging.getLogger("benefic.scoring")

# ──────────────────────────────────────────────
# 가중치 — HTML 폼 6개 항목과 1:1 대응
# ──────────────────────────────────────────────
W_AGE        = 0.25   # 연령
W_INCOME     = 0.25   # 소득 수준
W_FAMILY     = 0.15   # 가구 유형
W_REGION     = 0.10   # 지역
W_EMPLOYMENT = 0.15   # 취업 상태
W_DISABILITY = 0.10   # 장애 여부 (기존 W_SPECIAL 0.05 → 0.10으로 독립 승격)

SCORE_PASS = 0.6

# ──────────────────────────────────────────────
# 패널티 설정
# ──────────────────────────────────────────────
HARD_FAIL_KEYWORDS = ("나이 조건 미충족", "소득 조건 미충족")
PENALTY_BASE = 0.5   # 미충족 1개당 ×0.5

# ──────────────────────────────────────────────
# 2024년 기준 중위소득 월액 (만원) — 가구원수별
# ──────────────────────────────────────────────
MEDIAN_INCOME_MONTHLY = {1: 222, 2: 368, 3: 471, 4: 572, 5: 669, 6: 761}

def get_median_income_monthly(household_size: int) -> int:
    size = max(1, min(household_size, 6))
    return MEDIAN_INCOME_MONTHLY[size]


# ──────────────────────────────────────────────
# 1. 조건 파싱 유틸
# ──────────────────────────────────────────────
def _parse_age_range(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    text = str(text)
    m = re.search(r"(\d+)\s*[~\-]\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*세?\s*이상", text)
    if m:
        return int(m.group(1)), 150
    m = re.search(r"(\d+)\s*세?\s*이하", text)
    if m:
        return 0, int(m.group(1))
    m = re.search(r"(\d+)\s*세?\s*미만", text)
    if m:
        return 0, int(m.group(1)) - 1
    return None


def _parse_income_limit(text: str | None, household_size: int = 1) -> int | None:
    if not text:
        return None
    text = str(text)
    m = re.search(r"중위소득\s*(\d+)\s*%", text)
    if m:
        pct = int(m.group(1))
        monthly_median = get_median_income_monthly(household_size)
        return round(monthly_median * 12 * pct / 100)
    m = re.search(r"(\d[\d,]*)\s*만\s*원?\s*이하", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"(\d+)\s*억\s*이하", text)
    if m:
        return int(m.group(1)) * 10000
    return None


def _parse_age_from_fields(policy: dict) -> tuple[int, int] | None:
    for field in ("지원대상", "선정기준"):
        result = _parse_age_range(policy.get(field))
        if result is not None:
            return result
    return None


def _parse_income_from_fields(policy: dict, household_size: int = 1) -> int | None:
    for field in ("지원대상", "선정기준"):
        result = _parse_income_limit(policy.get(field), household_size)
        if result is not None:
            return result
    return None


# ──────────────────────────────────────────────
# 2. 단일 정책 스코어링
# ──────────────────────────────────────────────
def _score_one(user: dict, policy: dict) -> dict:
    # HTML 폼 6개 항목과 1:1 대응
    weights = np.zeros(6)
    max_w   = np.array([W_AGE, W_INCOME, W_FAMILY, W_REGION, W_EMPLOYMENT, W_DISABILITY])
    matched = []
    failed  = []

    household_size = user.get("가구원수", 1) or 1

    # ── [1] 연령 ─────────────────────────────────────────────
    age_range = _parse_age_from_fields(policy)
    if age_range:
        lo, hi = age_range
        if lo <= user.get("나이", 0) <= hi:
            weights[0] = W_AGE
            matched.append(f"나이 조건 충족 ({lo}~{hi}세)")
        else:
            failed.append(f"나이 조건 미충족 (기준 {lo}~{hi}세 / 입력 {user.get('나이')}세)")
    else:
        weights[0] = W_AGE  # 조건 명시 없으면 충족

    # ── [2] 소득 수준 ─────────────────────────────────────────
    income_limit = _parse_income_from_fields(policy, household_size)
    if income_limit:
        user_income = user.get("연소득", 0)
        if user_income <= income_limit:
            weights[1] = W_INCOME
            matched.append(f"소득 조건 충족 ({income_limit}만원 이하)")
        else:
            failed.append(f"소득 조건 미충족 (기준 {income_limit}만원 이하 / 입력 {user_income}만원)")
    else:
        weights[1] = W_INCOME

    # ── [3] 가구 유형 ─────────────────────────────────────────
    family_text = str(policy.get("지원대상") or "")
    user_family = user.get("가구유형", "")
    family_keywords = {
        "한부모": "한부모 가구",
        "다자녀": "다자녀 가구",
        "1인":    "1인 가구",
        "다문화": "다문화 가구",
        "조손":   "조손 가구",
        "노인":   "노인 단독 가구",
    }
    family_matched = False
    for kw, label in family_keywords.items():
        if kw in family_text:
            if kw in user_family:
                weights[2] = W_FAMILY
                matched.append(f"가구 조건 충족 ({label})")
                family_matched = True
            else:
                failed.append(f"가구 조건 미충족 (기준: {label})")
            break
    if not family_matched:
        weights[2] = W_FAMILY

    # ── [4] 지역 ─────────────────────────────────────────────
    region_text = str(policy.get("지원대상") or policy.get("소관기관명") or "")
    user_region = user.get("거주지역", "전국")
    sido_list   = ["서울", "경기", "부산", "인천", "대구", "광주", "대전", "울산",
                   "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]

    if user_region == "전국" or "전국" in region_text or not region_text:
        weights[3] = W_REGION
        matched.append("지역 조건 충족")
    else:
        policy_sido = [s for s in sido_list if s in region_text]
        if policy_sido:
            if any(s in user_region for s in policy_sido):
                weights[3] = W_REGION
                matched.append("지역 조건 충족")
            else:
                failed.append(f"지역 조건 미충족 (기준: {', '.join(policy_sido)} / 입력: {user_region})")
        else:
            weights[3] = W_REGION
            matched.append("지역 조건 충족")

    # ── [5] 취업 상태 ─────────────────────────────────────────
    employment_text = str(policy.get("지원대상") or "")
    user_emp = user.get("고용상태", "")
    emp_keywords = {
        "구직":    "구직자",
        "실업":    "구직자",
        "취업":    "취업자",
        "자영":    "자영업자",
        "육아휴직": "육아휴직 중",
        "학생":    "학생",
        "재직":    "취업자",
    }
    emp_matched = False
    for kw, label in emp_keywords.items():
        if kw in employment_text:
            if kw in user_emp or label in user_emp:
                weights[4] = W_EMPLOYMENT
                matched.append(f"고용 조건 충족 ({label})")
            else:
                failed.append(f"고용 조건 미충족 (기준: {label} / 입력: {user_emp})")
            emp_matched = True
            break
    if not emp_matched:
        weights[4] = W_EMPLOYMENT

    # ── [6] 장애 여부 (독립 항목으로 승격) ───────────────────
    disability_text = str(policy.get("지원대상") or "")
    user_disability = user.get("장애여부", "없음")

    if "장애" in disability_text:
        if user_disability != "없음":
            weights[5] = W_DISABILITY
            matched.append(f"장애 조건 충족 ({user_disability})")
        else:
            # 장애인 전용 정책인데 장애 없음 → 하드 탈락 수준
            failed.append("장애 조건 미충족 (장애인 대상 정책)")
            weights[5] = 0.0
    elif "국가유공자" in disability_text:
        if user.get("국가유공자"):
            weights[5] = W_DISABILITY
            matched.append("국가유공자 조건 충족")
        else:
            failed.append("국가유공자 조건 미충족")
            weights[5] = 0.0
    else:
        # 장애 조건 명시 없는 정책 → 장애여부 무관, 가중치 전액 충족
        weights[5] = W_DISABILITY

    # ── 최종 점수 계산 ────────────────────────────────────────
    raw_score = float(np.sum(weights))
    max_score = float(np.sum(max_w))
    score     = round(raw_score / max_score, 4) if max_score > 0 else 0.0

    # 핵심 조건(나이·소득) 미충족 → 즉시 0점
    hard_failed = any(kw in f for f in failed for kw in HARD_FAIL_KEYWORDS)
    if hard_failed:
        score = 0.0
    elif failed:
        penalty = PENALTY_BASE ** len(failed)
        score   = round(score * penalty, 4)
        log.debug("패널티 적용: 미충족 %d개 → ×%.3f", len(failed), penalty)

    # FAISS 유사도 30% 반영
    faiss_score = float(policy.get("score", 0.5))
    final_score = round(score * 0.7 + faiss_score * 0.3, 4)

    return {
        "score":       final_score,
        "pass":        final_score >= SCORE_PASS,
        "matched":     matched,
        "failed":      failed,
        "hard_failed": hard_failed,
    }


# ──────────────────────────────────────────────
# 3. 공개 인터페이스
# ──────────────────────────────────────────────
def score_policies(user: dict, policies: list[dict]) -> list[dict]:
    """
    사용자 정보 + 정책 리스트 → 스코어링 결과 반환 (score 내림차순)

    user dict 필수 키 (HTML 폼 6개 항목과 1:1):
      나이, 연소득, 가구유형, 가구원수, 거주지역, 고용상태, 장애여부
    """
    results = []
    for policy in policies:
        scored = _score_one(user, policy)
        results.append({**policy, **scored})

    results.sort(key=lambda x: x["score"], reverse=True)
    log.info(
        "스코어링 완료: 전체 %d건 / 수급 가능 %d건 / 하드 탈락 %d건",
        len(results),
        sum(1 for r in results if r["pass"]),
        sum(1 for r in results if r["hard_failed"]),
    )
    return results


# ──────────────────────────────────────────────
# 4. 결과 출력 유틸
# ──────────────────────────────────────────────
def print_scored(results: list[dict]) -> None:
    passed = [r for r in results if r["pass"]]
    failed = [r for r in results if not r["pass"]]

    print(f"\n{'═' * 60}")
    print(f"  수급 가능성 스코어링 결과")
    print(f"  수급 가능: {len(passed)}건  /  검토 필요: {len(failed)}건")
    print(f"{'═' * 60}")

    for r in results:
        if r["hard_failed"]:
            status = "🚫 핵심조건 탈락"
        elif r["pass"]:
            status = "✅ 수급 가능"
        else:
            status = "❌ 조건 미충족"

        print(f"\n{status}  [{r['score']:.2f}]  {r.get('서비스명', '-')}")
        print(f"  기관  : {r.get('소관기관명', '-')}")
        print(f"  유형  : {r.get('지원유형', '-')}")
        if r["matched"]:
            print(f"  충족  : {' / '.join(r['matched'])}")
        if r["failed"]:
            print(f"  미충족: {' / '.join(r['failed'])}")

    print(f"\n{'═' * 60}\n")


# ──────────────────────────────────────────────
# 5. 단독 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    from user_input import get_user_input
    from policy_search import search_policies

    user     = get_user_input()
    policies = search_policies(user, top_k=10)
    results  = score_policies(user, policies)
    print_scored(results)
