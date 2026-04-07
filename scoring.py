
from __future__ import annotations

import logging
import re
from typing import Iterable

log = logging.getLogger("benefic.scoring")

# 제출용 최종 보수형 스코어러
# 목표:
# 1) 지역/가구 전용 정책 오추천 최소화
# 2) "6천만원 -> 6만원", "부양자녀 100만원 -> 신청자 소득기준" 같은 오파싱 방지
# 3) 하드 조건은 과감히 탈락, 애매한 건 soft-fail로 남겨 점수만 낮춤

BASE_SCORE = 0.45
BONUS_REGION = 0.20
BONUS_EMP = 0.15
SCORE_PASS = 0.60
SOFT_PENALTY = 0.10
INCOME_WARN_RATIO = 0.85

MEDIAN_INCOME_MONTHLY = {1: 222, 2: 368, 3: 471, 4: 572, 5: 669, 6: 761}
SIDO_LIST = [
    "서울", "경기", "부산", "인천", "대구", "광주", "대전", "울산",
    "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]
CENTRAL_ORGS = [
    "보건복지부", "고용노동부", "국토교통부", "교육부", "여성가족부",
    "국세청", "중소벤처기업부", "법무부", "금융위원회", "행정안전부"
]
CHILD_CONTEXT = ["아동", "자녀", "영아", "청소년", "직계존속", "부양자녀", "출생", "혼인기간", "임신", "출산"]
LOCAL_ORG_HINTS = ["특별시", "광역시", "도", "시", "군", "구"]
CRISIS_KEYWORDS = ["위기상황", "생계유지 곤란", "실직", "휴업", "폐업", "화재", "자연재해", "중한 질병", "부상", "가정폭력", "성폭력", "노숙"]


def _get_median_income_monthly(household_size: int) -> int:
    return MEDIAN_INCOME_MONTHLY[max(1, min(int(household_size or 1), 6))]


def _extract_field(text: str, field: str) -> str:
    m = re.search(rf"{field}:\s*(.+?)(?:\n|$)", str(text or ""))
    return m.group(1).strip() if m else ""


def _policy_texts(policy: dict) -> list[str]:
    evidence = str(policy.get("evidence_text") or "")
    return [
        str(policy.get("지원대상") or ""),
        str(policy.get("지원내용") or ""),
        str(policy.get("선정기준") or ""),
        _extract_field(evidence, "지원대상"),
        _extract_field(evidence, "지원내용"),
        _extract_field(evidence, "선정기준"),
        evidence,
    ]


def _norm_user(user: dict) -> dict:
    return {
        "나이": user.get("나이") or user.get("age") or 0,
        "거주지역": user.get("거주지역") or user.get("region") or "전국",
        "연소득": user.get("연소득") or user.get("annual_income") or 0,
        "가구원수": user.get("가구원수") or user.get("household_size") or 1,
        "고용상태": user.get("고용상태") or user.get("employment_status") or "",
        "가구유형": user.get("가구유형") or user.get("household_type") or "",
        "장애여부": user.get("장애여부") or ("있음" if user.get("disability") not in [None, "", "없음", False] else "없음"),
        "국가유공자": bool(user.get("국가유공자") or user.get("veteran")),
        "다문화가구": bool(user.get("다문화가구") or user.get("multicultural")),
    }


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(k in text for k in keywords)


def _parse_age_range(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    text = str(text)

    m = re.search(r"만?\s*(\d+)\s*세\s*(?:이상|초과)\s*[~〜\-,\s]*\s*만?\s*(\d+)\s*세\s*(?:이하|미만)", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)

    m = re.search(r"(\d+)\s*[~\-]\s*(\d+)\s*세", text)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo, hi) if lo <= hi else (hi, lo)

    m = re.search(r"만?\s*(\d+)\s*세\s*이상", text)
    if m:
        return int(m.group(1)), 120

    m = re.search(r"만?\s*(\d+)\s*세\s*이하", text)
    if m:
        return 0, int(m.group(1))

    m = re.search(r"만?\s*(\d+)\s*세\s*미만", text)
    if m:
        return 0, int(m.group(1)) - 1

    return None


def _parse_money_to_manwon(text: str) -> int | None:
    t = str(text or "").replace(",", "").replace(" ", "")
    # 1억 / 1억원 / 1억2천 / 7천5백만원 / 2200만원 / 100만원
    m = re.search(r"(\d+)억(?:(\d+)천)?(?:(\d+)백)?만?원?", t)
    if m:
        eok = int(m.group(1))
        cheon = int(m.group(2)) if m.group(2) else 0
        baek = int(m.group(3)) if m.group(3) else 0
        return eok * 10000 + cheon * 1000 + baek * 100

    m = re.search(r"(\d+)천(\d+)백만원?", t)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2)) * 100

    m = re.search(r"(\d+)천만원?", t)
    if m:
        return int(m.group(1)) * 1000

    m = re.search(r"(\d+)백만원?", t)
    if m:
        return int(m.group(1)) * 100

    m = re.search(r"(\d+)만원?", t)
    if m:
        return int(m.group(1))

    return None


def _line_is_user_income_gate(line: str) -> bool:
    line = str(line or "")
    if not line:
        return False

    # 신청자 본인 소득 기준이 아닌 보조조건들은 제외
    if _contains_any(line, ["부양자녀", "직계존속", "배우자 각각", "총급여액 등이 3백만원", "연간소득금액 100만원"]):
        return False

    if _contains_any(line, ["중위소득", "연소득", "총소득", "건강보험료", "보험료"]):
        return True

    # 금액만 나와도 소득/급여 문맥이 있으면 허용
    if ("소득" in line or "급여" in line or "보험료" in line) and _parse_money_to_manwon(line) is not None:
        return True

    return False


def _parse_income_limit(line: str | None, household_size: int = 1) -> int | None:
    if not line:
        return None
    text = str(line).replace(",", "").strip()

    m = re.search(r"중위소득\s*(\d+)\s*%", text)
    if m:
        pct = int(m.group(1))
        return round(_get_median_income_monthly(household_size) * 12 * pct / 100)

    money = _parse_money_to_manwon(text)
    if money is not None and _line_is_user_income_gate(text):
        return money

    return None


def _parse_applicant_age_from_fields(policy: dict) -> tuple[int, int] | None:
    for text in _policy_texts(policy):
        if not text:
            continue
        for line in re.split(r"[\n\r]", text):
            line = line.strip()
            if not line:
                continue
            if _contains_any(line, CHILD_CONTEXT):
                continue
            if _contains_any(line, ["지원대상", "대상", "청년", "노인", "중장년"]):
                parsed = _parse_age_range(line)
                if parsed is not None:
                    return parsed
    return None


def _infer_income_limit_from_household_block(evidence: str, household_size: int) -> int | None:
    # 근로·자녀장려금 같은 가구유형별 소득 기준 처리
    lines = [ln.strip() for ln in re.split(r"[\n\r]", str(evidence or "")) if ln.strip()]
    desired_keys = []
    if household_size == 1:
        desired_keys = ["단독가구"]
    elif household_size >= 2:
        desired_keys = ["홑벌이", "맞벌이"]

    for key in desired_keys:
        for line in lines:
            if key in line and ("미만" in line or "이하" in line):
                money = _parse_money_to_manwon(line)
                if money is not None:
                    return money
    return None


def _parse_income_from_fields(policy: dict, household_size: int = 1) -> int | None:
    evidence = str(policy.get("evidence_text") or "")

    block_limit = _infer_income_limit_from_household_block(evidence, household_size)
    if block_limit is not None:
        return block_limit

    limits: list[int] = []
    for text in _policy_texts(policy):
        if not text:
            continue
        for line in re.split(r"[\n\r]", text):
            line = line.strip()
            if not line or not _line_is_user_income_gate(line):
                continue
            limit = _parse_income_limit(line, household_size)
            if limit is not None:
                limits.append(limit)

    if not limits:
        return None

    # 여러 기준이 섞여 있으면 가장 보수적이되, 너무 작은 보조조건 숫자(예: 100만원)는 제거
    cleaned = [x for x in limits if x >= 500] or limits
    return max(cleaned)


def _extract_policy_regions(policy: dict) -> list[str]:
    text = " ".join([
        str(policy.get("region") or ""),
        str(policy.get("소관기관명") or ""),
        str(policy.get("지원대상") or ""),
        str(policy.get("선정기준") or ""),
        str(policy.get("evidence_text") or ""),
    ])
    regions = []
    for sido in SIDO_LIST:
        if sido in text and sido not in regions:
            regions.append(sido)
    return regions


def _is_nationwide_policy(policy: dict) -> bool:
    region_field = str(policy.get("region") or "").strip()
    org = str(policy.get("소관기관명") or "").strip()
    text = " ".join([
        region_field,
        org,
        str(policy.get("지원대상") or ""),
        str(policy.get("선정기준") or ""),
    ])

    if region_field == "전국":
        return True

    # region이 특정 지역이면 전국으로 보지 않음
    if any(s in region_field for s in SIDO_LIST):
        return False

    # 중앙부처 + 지역 명시 없음일 때만 전국으로 간주
    if any(org_name in org for org_name in CENTRAL_ORGS):
        if not any(local in text for local in SIDO_LIST):
            return True

    return False


def _crisis_policy(policy: dict) -> bool:
    text = " ".join(_policy_texts(policy))
    return _contains_any(text, CRISIS_KEYWORDS)


def _family_gate_reason(user: dict, policy: dict) -> str | None:
    head_text = " ".join([
        str(policy.get("지원대상") or ""),
        str(policy.get("선정기준") or ""),
    ])
    full_text = " ".join([
        head_text,
        str(policy.get("지원내용") or ""),
        str(policy.get("evidence_text") or ""),
    ])
    user_family = str(user.get("가구유형", "") or "")
    one_person = ("1인" in user_family) or int(user.get("가구원수", 1) or 1) == 1

    # 전연령/일반 임차인처럼 폭넓은 대상에게 가족별 소득기준만 병기된 정책은 전용 정책으로 보지 않음
    broad_target = bool(re.search(r"(전연령|전\s*세대|무주택\s*임차인|전체\s*가구|일반\s*가구)", head_text))

    def head_or_full(pattern: str) -> bool:
        if re.search(pattern, head_text):
            return True
        if broad_target:
            return False
        return re.search(pattern, full_text) is not None

    if head_or_full(r"(신혼부부|혼인기간\s*\d+년)"):
        if not re.search(r"(신혼|기혼|부부)", user_family):
            return "가구 조건 미충족 (기준: 신혼부부 전용)"

    if head_or_full(r"(한부모가구|한부모 가족|한부모가족증명서)"):
        if "한부모" not in user_family:
            return "가구 조건 미충족 (기준: 한부모 가구)"

    if head_or_full(r"(미혼모|미혼부)"):
        if not re.search(r"(미혼모|미혼부|한부모)", user_family):
            return "가구 조건 미충족 (기준: 미혼모·부 전용)"

    if head_or_full(r"(다자녀 가구|다자녀가정|자녀가 2명)"):
        if "다자녀" not in user_family:
            return "가구 조건 미충족 (기준: 다자녀 가구)"

    if head_or_full(r"(임산부|출산가구|출산 후 1년|영아를 양육)"):
        if one_person and not re.search(r"(임산부|출산|영아|자녀|부부)", user_family):
            return "가구 조건 미충족 (기준: 임신·출산·양육 가구 전용)"

    return None


def _special_gate_reason(user: dict, policy: dict) -> str | None:
    target = " ".join(_policy_texts(policy))

    if re.search(r"(장애인 대상|등록장애인|중증장애인 대상|장애인 가구)", target):
        if user.get("장애여부", "없음") == "없음":
            return "장애 조건 미충족 (장애인 대상 전용 정책)"

    if "국가유공자" in target and not user.get("국가유공자"):
        return "국가유공자 조건 미충족 (국가유공자 전용 정책)"

    if "다문화" in target and not user.get("다문화가구"):
        return "다문화가구 조건 미충족 (다문화가구 전용 정책)"

    return None


def _check_gates(user: dict, policy: dict) -> tuple[bool, list[str]]:
    household_size = int(user.get("가구원수", 1) or 1)
    failures: list[str] = []

    # 1) 지역은 가장 먼저 강하게 거름
    user_region = str(user.get("거주지역", "전국") or "전국")
    if not _is_nationwide_policy(policy):
        policy_regions = _extract_policy_regions(policy)
        user_region_kw = next((s for s in SIDO_LIST if s in user_region), None)
        if policy_regions and user_region_kw and user_region_kw not in policy_regions:
            failures.append(f"지역 조건 미충족 (정책 대상 지역: {', '.join(policy_regions)} / 입력: {user_region})")

    # 2) 명시적 전용 정책 하드게이트
    family_reason = _family_gate_reason(user, policy)
    if family_reason:
        failures.append(family_reason)

    special_reason = _special_gate_reason(user, policy)
    if special_reason:
        failures.append(special_reason)

    # 3) 나이
    age_range = _parse_applicant_age_from_fields(policy)
    if age_range is not None:
        lo, hi = age_range
        user_age = int(user.get("나이", 0) or 0)
        if not (lo <= user_age <= hi):
            failures.append(f"나이 조건 미충족 (기준 {lo}~{hi}세 / 입력 {user_age}세)")

    # 4) 소득
    income_limit = _parse_income_from_fields(policy, household_size)
    if income_limit is not None:
        user_income = int(user.get("연소득", 0) or 0)
        if user_income > income_limit:
            failures.append(f"소득 조건 미충족 (기준 {income_limit}만원 이하 / 입력 {user_income}만원)")

    return len(failures) == 0, failures


def _calc_bonus(user: dict, policy: dict) -> tuple[float, list[str], list[str]]:
    bonus = 0.0
    matched: list[str] = []
    soft_failed: list[str] = []

    household_size = int(user.get("가구원수", 1) or 1)
    user_region = str(user.get("거주지역", "전국") or "전국")

    # region
    if _is_nationwide_policy(policy):
        bonus += BONUS_REGION
        matched.append("지역 조건 충족 (전국)")
    else:
        policy_regions = _extract_policy_regions(policy)
        user_region_kw = next((s for s in SIDO_LIST if s in user_region), None)
        if user_region_kw and user_region_kw in policy_regions:
            bonus += BONUS_REGION
            matched.append(f"지역 조건 충족 ({user_region_kw})")

    # employment
    target_text = " ".join(_policy_texts(policy))
    user_emp = str(user.get("고용상태", "") or "")

    if _contains_any(target_text, ["미취업", "실업", "구직"]):
        if _contains_any(user_emp, ["구직", "미취업", "실업"]):
            bonus += BONUS_EMP
            matched.append("고용 조건 충족 (구직·미취업)")
        else:
            soft_failed.append(f"고용 상태 불일치 (정책 권장: 구직·미취업 / 입력: {user_emp or '미입력'})")

    elif re.search(r"(?<!미)취업|재직|근로", target_text):
        if _contains_any(user_emp, ["취업", "재직", "근로"]):
            bonus += BONUS_EMP
            matched.append("고용 조건 충족 (취업·재직)")
        else:
            soft_failed.append(f"고용 상태 불일치 (정책 권장: 취업·재직 / 입력: {user_emp or '미입력'})")
    else:
        bonus += BONUS_EMP
        matched.append("고용 조건 제한 없음")

    # 소득 경고는 근접할 때만
    income_limit = _parse_income_from_fields(policy, household_size)
    if income_limit and income_limit > 0:
        user_income = int(user.get("연소득", 0) or 0)
        ratio = user_income / income_limit
        if INCOME_WARN_RATIO <= ratio <= 1.0:
            soft_failed.append(f"소득 한도 근접 경고 (한도 {income_limit}만원 대비 {int(ratio * 100)}% 사용 중 — 소득 변동 시 탈락 위험)")

    # 긴급/위기 정책은 사용자 위기정보가 없으면 보수적으로 soft-fail
    if _crisis_policy(policy):
        soft_failed.append("위기상황 확인 필요 (긴급지원 성격 정책)")

    return round(bonus, 4), matched, soft_failed


def _score_one(user: dict, policy: dict) -> dict:
    gate_passed, gate_failures = _check_gates(user, policy)
    if not gate_passed:
        return {
            "score": 0.0,
            "pass": False,
            "matched": [],
            "failed": gate_failures,
            "soft_failed": [],
            "hard_failed": True,
        }

    bonus, bonus_matched, soft_failed = _calc_bonus(user, policy)
    final_score = BASE_SCORE + bonus - (SOFT_PENALTY * len(soft_failed))
    final_score = round(max(0.0, min(0.95, final_score)), 4)

    return {
        "score": final_score,
        "pass": final_score >= SCORE_PASS,
        "matched": bonus_matched,
        "failed": [],
        "soft_failed": soft_failed,
        "hard_failed": False,
    }


def score_policies(user: dict, policies: list[dict]) -> list[dict]:
    norm_user = _norm_user(user)
    results = []
    for policy in policies:
        results.append({**policy, **_score_one(norm_user, policy)})
    results.sort(key=lambda x: x["score"], reverse=True)
    log.info(
        "스코어링 완료: 전체 %d건 / 수급 가능 %d건 / Gate 탈락 %d건",
        len(results),
        sum(1 for r in results if r["pass"]),
        sum(1 for r in results if r["hard_failed"]),
    )
    return results
