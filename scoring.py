"""
07 수급 가능성 스코어링 (v2.1 — soft_failed 추가)
=================================================
v2 대비 변경사항:
  - [FIX] Gate 통과 정책에도 soft_failed 리스트 생성
    기존: Gate 통과 시 failed = [] → GPT에 미충족 정보 없이 전달
    수정: Gate 통과 후에도 잠재 리스크(소득 여유도, 지역, 고용 미일치 등)를
          soft_failed에 담아 GPT 프롬프트에 전달
    효과: GPT가 구체적인 탈락사유/해결방법을 풍부하게 생성 가능

  - [FIX] _calc_bonus()에서 지역·고용 미일치 시 soft_failed에 추가
  - [FIX] 소득 여유도 경고 추가 (한도 대비 80% 이상 사용 시 경고)
  - [FIX] 다문화가구 Gate 추가 (다문화 전용 정책 처리)

점수 구조 (Gate 통과 후):
  base_score = 0.50
  + 지역 일치      +0.20
  + 고용상태 일치  +0.20
  ──────────────────────
  max = 1.00
"""

from __future__ import annotations

import re
import logging

log = logging.getLogger("benefic.scoring")

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
BASE_SCORE        = 0.50
BONUS_REGION      = 0.20
BONUS_EMP         = 0.20
SCORE_PASS        = 0.50
INCOME_WARN_RATIO = 0.80   # 소득 한도 대비 이 비율 이상이면 soft 경고

MEDIAN_INCOME_MONTHLY = {1: 222, 2: 368, 3: 471, 4: 572, 5: 669, 6: 761}

SIDO_LIST = [
    "서울", "경기", "부산", "인천", "대구", "광주", "대전", "울산",
    "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]


# ──────────────────────────────────────────────
# 1. 파싱 유틸
# ──────────────────────────────────────────────
def _get_median_income_monthly(household_size: int) -> int:
    return MEDIAN_INCOME_MONTHLY[max(1, min(household_size, 6))]


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
        return round(_get_median_income_monthly(household_size) * 12 * pct / 100)
    m = re.search(r"(\d[\d,]*)\s*만\s*원?\s*이하", text)
    if m:
        return int(m.group(1).replace(",", ""))
    m = re.search(r"(\d+)\s*억\s*이하", text)
    if m:
        return int(m.group(1)) * 10000
    return None


def _parse_age_from_fields(policy: dict) -> tuple[int, int] | None:
    for field in ("지원대상", "선정기준"):
        r = _parse_age_range(policy.get(field))
        if r is not None:
            return r
    return None


def _parse_income_from_fields(policy: dict, household_size: int = 1) -> int | None:
    for field in ("지원대상", "선정기준"):
        r = _parse_income_limit(policy.get(field), household_size)
        if r is not None:
            return r
    return None


# ──────────────────────────────────────────────
# 2. Gate 체크 — 필수 조건
# ──────────────────────────────────────────────
def _check_gates(user: dict, policy: dict) -> tuple[bool, list[str]]:
    """
    필수 조건 검사.
    Returns (all_passed, gate_failures)
    """
    household_size = user.get("가구원수", 1) or 1
    failures: list[str] = []

    # Gate 1: 연령
    age_range = _parse_age_from_fields(policy)
    if age_range is not None:
        lo, hi = age_range
        user_age = user.get("나이", 0)
        if not (lo <= user_age <= hi):
            failures.append(f"나이 조건 미충족 (기준 {lo}~{hi}세 / 입력 {user_age}세)")

    # Gate 2: 소득
    income_limit = _parse_income_from_fields(policy, household_size)
    if income_limit is not None:
        user_income = user.get("연소득", 0)
        if user_income > income_limit:
            failures.append(
                f"소득 조건 미충족 (기준 {income_limit}만원 이하 / 입력 {user_income}만원)"
            )

    # Gate 3: 가구 유형 전용
    target_text = str(policy.get("지원대상") or "")
    user_family = user.get("가구유형", "")
    FAMILY_GATES = {
        "한부모": "한부모 가구",
        "다자녀": "다자녀 가구",
        "조손":   "조손 가구",
        "노인":   "노인 단독 가구",
    }
    for kw, label in FAMILY_GATES.items():
        if kw in target_text and kw not in user_family:
            failures.append(f"가구 조건 미충족 (기준: {label} 전용)")
            break

    # Gate 4: 장애인 / 국가유공자 전용
    user_disability = user.get("장애여부", "없음")
    is_disability_policy = "장애" in target_text
    is_veteran_policy    = "국가유공자" in target_text

    if is_disability_policy and not is_veteran_policy:
        if user_disability == "없음":
            failures.append("장애 조건 미충족 (장애인 대상 전용 정책)")
    elif is_veteran_policy:
        if not user.get("국가유공자"):
            failures.append("국가유공자 조건 미충족 (국가유공자 전용 정책)")

    # Gate 5: 다문화가구 전용
    if "다문화" in target_text and not user.get("다문화가구"):
        failures.append("다문화가구 조건 미충족 (다문화가구 전용 정책)")

    return len(failures) == 0, failures


# ──────────────────────────────────────────────
# 3. Bonus + soft_failed 계산
# ──────────────────────────────────────────────
def _calc_bonus(user: dict, policy: dict) -> tuple[float, list[str], list[str]]:
    """
    Gate 통과 후 보조 조건 가점 + 잠재 리스크(soft_failed) 계산.

    Returns
    -------
    (bonus, bonus_matched, soft_failed)
      soft_failed: Gate는 통과했지만 GPT가 탈락사유로 활용할 수 있는 잠재 위험 목록
    """
    bonus: float = 0.0
    matched: list[str] = []
    soft_failed: list[str] = []

    household_size = user.get("가구원수", 1) or 1
    target_text    = str(policy.get("지원대상") or policy.get("소관기관명") or "")
    user_region    = user.get("거주지역", "전국")

    # ── Bonus 1: 지역 ────────────────────────────────────────
    if user_region == "전국" or "전국" in target_text or not target_text:
        bonus += BONUS_REGION
        matched.append("지역 조건 충족")
    else:
        policy_sido = [s for s in SIDO_LIST if s in target_text]
        if not policy_sido:
            bonus += BONUS_REGION
            matched.append("지역 조건 충족 (전국)")
        elif any(s in user_region for s in policy_sido):
            bonus += BONUS_REGION
            matched.append(f"지역 조건 충족 ({', '.join(policy_sido)})")
        else:
            # 지역 미일치 — Gate는 아니지만 soft 경고
            soft_failed.append(
                f"지역 조건 불일치 (정책 대상 지역: {', '.join(policy_sido)} / 입력: {user_region})"
            )

    # ── Bonus 2: 고용 상태 ───────────────────────────────────
    user_emp = user.get("고용상태", "")
    EMP_KEYWORDS = {
        "구직": "구직자",
        "실업": "구직자",
        "취업": "취업자",
        "재직": "취업자",
        "자영": "자영업자",
        "육아휴직": "육아휴직 중",
        "학생": "학생",
    }
    emp_condition_found = False
    for kw, label in EMP_KEYWORDS.items():
        if kw in target_text:
            emp_condition_found = True
            if kw in user_emp or label in user_emp:
                bonus += BONUS_EMP
                matched.append(f"고용 조건 충족 ({label})")
            else:
                soft_failed.append(
                    f"고용 상태 불일치 (정책 권장: {label} / 입력: {user_emp or '미입력'})"
                )
            break
    if not emp_condition_found:
        bonus += BONUS_EMP
        matched.append("고용 조건 제한 없음")

    # ── Soft: 소득 여유도 경고 ───────────────────────────────
    income_limit = _parse_income_from_fields(policy, household_size)
    if income_limit and income_limit > 0:
        user_income = user.get("연소득", 0)
        ratio = user_income / income_limit
        if ratio >= INCOME_WARN_RATIO:
            soft_failed.append(
                f"소득 한도 근접 경고 (한도 {income_limit}만원 대비 {int(ratio * 100)}% 사용 중 — "
                f"소득 변동 시 탈락 위험)"
            )

    # ── Soft: 연령 경계 경고 ─────────────────────────────────
    age_range = _parse_age_from_fields(policy)
    if age_range:
        lo, hi = age_range
        user_age = user.get("나이", 0)
        margin = 2  # 경계 2세 이내면 경고
        if lo <= user_age <= lo + margin:
            soft_failed.append(
                f"연령 하한 근접 (기준 {lo}세 이상 / 현재 {user_age}세 — "
                f"향후 재신청 시 연령 재확인 불필요)"
            )
        elif hi - margin <= user_age <= hi:
            soft_failed.append(
                f"연령 상한 근접 (기준 {hi}세 이하 / 현재 {user_age}세 — "
                f"다음 연도 갱신 시 연령 초과 탈락 가능)"
            )

    # ── Soft: 가구원수 적정성 ────────────────────────────────
    user_family = user.get("가구유형", "")
    if "1인" in user_family and household_size > 1:
        soft_failed.append(
            f"가구유형-가구원수 불일치 (1인 가구로 입력했으나 가구원수 {household_size}명 — 서류 제출 시 확인 필요)"
        )

    # [BUG FIX] "서류 미비 가능성" 일반 경고 제거
    # 모든 정책에 동일하게 붙는 공통 문구 → GPT 프롬프트에서 금지된 문구와 동일
    # analysis.py 프롬프트 규칙 ④와 충돌: GPT가 이를 근거로 탈락사유를 불필요하게 채우는 버그 원인

    return round(bonus, 4), matched, soft_failed


# ──────────────────────────────────────────────
# 4. 단일 정책 스코어링
# ──────────────────────────────────────────────
def _score_one(user: dict, policy: dict) -> dict:
    """
    Gate → Bonus 순서로 점수 계산.

    반환 구조:
      score       : 최종 점수 (0.0 ~ 1.0)
      pass        : score >= SCORE_PASS
      matched     : 충족 조건 리스트
      failed      : Gate 탈락 사유 (Gate 통과 시 빈 리스트)
      soft_failed : 잠재 리스크 — Gate 통과 정책에도 채워짐 [★ 신규]
      hard_failed : Gate 탈락 여부
    """
    # Step 1: Gate
    gate_passed, gate_failures = _check_gates(user, policy)

    if not gate_passed:
        return {
            "score":       0.0,
            "pass":        False,
            "matched":     [],
            "failed":      gate_failures,
            "soft_failed": [],
            "hard_failed": True,
        }

    # Step 2: Bonus + soft_failed
    bonus, bonus_matched, soft_failed = _calc_bonus(user, policy)
    final_score = round(BASE_SCORE + bonus, 4)

    return {
        "score":       final_score,
        "pass":        final_score >= SCORE_PASS,
        "matched":     bonus_matched,
        "failed":      [],
        "soft_failed": soft_failed,   # ★ GPT 탈락사유 생성에 활용
        "hard_failed": False,
    }


# ──────────────────────────────────────────────
# 5. 공개 인터페이스
# ──────────────────────────────────────────────
def score_policies(user: dict, policies: list[dict]) -> list[dict]:
    """
    사용자 정보 + 정책 리스트 → 스코어링 결과 반환 (score 내림차순)
    """
    results = []
    for policy in policies:
        scored = _score_one(user, policy)
        results.append({**policy, **scored})

    results.sort(key=lambda x: x["score"], reverse=True)

    n_pass      = sum(1 for r in results if r["pass"])
    n_hard_fail = sum(1 for r in results if r["hard_failed"])
    log.info(
        "스코어링 완료: 전체 %d건 / 수급 가능 %d건 / Gate 탈락 %d건",
        len(results), n_pass, n_hard_fail,
    )
    return results


# ──────────────────────────────────────────────
# 6. 결과 출력 유틸
# ──────────────────────────────────────────────
def print_scored(results: list[dict]) -> None:
    passed = [r for r in results if r["pass"]]
    failed = [r for r in results if not r["pass"]]

    print(f"\n{'═' * 60}")
    print(f"  수급 가능성 스코어링 결과")
    print(f"  수급 가능: {len(passed)}건  /  탈락: {len(failed)}건")
    print(f"{'═' * 60}")

    for r in results:
        if r["hard_failed"]:
            status = "🚫 필수조건 탈락"
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
            print(f"  탈락  : {' / '.join(r['failed'])}")
        if r.get("soft_failed"):
            print(f"  리스크: {' / '.join(r['soft_failed'])}")

    print(f"\n{'═' * 60}\n")


# ──────────────────────────────────────────────
# 7. 단독 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    from user_input import get_user_input
    from policy_search import search_policies

    user     = get_user_input()
    policies = search_policies(user, top_k=10)
    results  = score_policies(user, policies)
    print_scored(results)
