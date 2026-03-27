"""
08 탈락 사유 분석 + 09 복지 포트폴리오 추천 + 10 요약 생성
============================================================
v2.2 변경사항:
  - [FIX] 탈락사유 프롬프트 규칙 전면 재작성
    기존: "반드시 2개 이상" 강제 + 서류미비·행정지연 fallback 허용
    수정: 미충족조건/소프트경고 없으면 빈 배열([]) 반환, 일반적 문구 금지
    효과: 모든 정책에 "서류 미비 가능성" 반복 출력 문제 해결
  - [FIX] 해결방법 → 행동 가이드 리네임, 탈락사유 1:1 대응 구체적 액션으로 교체
    금지: "필요한 서류를 준비합니다" 등 공통 문구
    허용: 기관명·수치·신청처 포함한 이 정책 고유의 행동 가이드
  - [FIX] 탈락사유 없는 정책 터미널 출력: "✅ 탈락 사유 없음 — 조건 충족" 표시
  - [유지] policy_id slug 생성 방식 main.py _make_slug()와 동일하게 유지
  - [유지] top_policies[:10] 유지
"""

from __future__ import annotations

import json
import os
import re
import logging

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

log = logging.getLogger("benefic.analysis")

MODEL = "gpt-4o-mini"


# ── policy_id slug 생성 (main.py _make_slug와 동일 로직) ─────
def _make_slug(name: str, idx: int = 0) -> str:
    slug = re.sub(r"[^\w가-힣]", "-", name).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    return slug or f"policy-{idx}"


# ── CSS 클래스 매핑 ──────────────────────────────────────────
def _score_to_css(score: int) -> dict:
    if score >= 80:
        return {
            "card_class":     "top",
            "percent_class":  "high",
            "progress_color": "green",
            "icon_color":     "green",
            "badge_class":    "badge-green",
            "badge_label":    "✅ 조건 충족",
        }
    elif score >= 60:
        return {
            "card_class":     "mid",
            "percent_class":  "mid",
            "progress_color": "blue",
            "icon_color":     "blue",
            "badge_class":    "badge-blue",
            "badge_label":    "⚡ 확인 필요",
        }
    else:
        return {
            "card_class":     "low",
            "percent_class":  "low",
            "progress_color": "orange",
            "icon_color":     "orange",
            "badge_class":    "badge-orange",
            "badge_label":    "⚠️ 조건 부족",
        }


# ── 1. GPT-4o mini 호출 ──────────────────────────────────────
def _call_gpt(user: dict, policies: list[dict]) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY 환경변수가 설정되지 않았습니다.\n"
            ".env 파일에 OPENAI_API_KEY=sk-... 를 추가하거나\n"
            "환경변수로 직접 설정하세요."
        )

    client = OpenAI(api_key=api_key)
    top_policies = policies[:10]

    policy_text = ""
    for i, p in enumerate(top_policies, 1):
        # [FIX] soft_failed 항목을 "잠재리스크" 필드로 별도 전달
        soft_failed_text = ', '.join(p.get('soft_failed', [])) or '없음'
        failed_text      = ', '.join(p.get('failed', [])) or '없음'
        matched_text     = ', '.join(p.get('matched', [])) or '없음'

        policy_text += f"""
[정책 {i}]
- 서비스명: {p.get('서비스명', '-')}
- 지원유형: {p.get('지원유형', '-')}
- 지원대상: {p.get('지원대상', p.get('소관기관명', '-'))}
- 수급확률(rule-based): {int(p.get('score', 0) * 100)}%
- 충족조건: {matched_text}
- 미충족조건(필수탈락): {failed_text}
- 잠재리스크(소프트경고): {soft_failed_text}
"""

    prompt = f"""
역할: 복지 정책 분석 전문가 및 프론트엔드 데이터 엔지니어

작업:
제공된 사용자 정보와 정책 데이터를 분석하여, '베네픽(Benefic) v2.0' HTML 대시보드에
직접 렌더링될 수 있는 JSON 데이터를 생성하라.

[사용자 정보]
- 나이: {user.get('나이')}세
- 연소득: {user.get('연소득')}만원
- 가구유형: {user.get('가구유형')}
- 가구원수: {user.get('가구원수')}명
- 거주지역: {user.get('거주지역')}
- 고용상태: {user.get('고용상태')}
- 장애여부: {user.get('장애여부')}
- 국가유공자: {'예' if user.get('국가유공자') else '아니오'}
- 다문화가구: {'예' if user.get('다문화가구') else '아니오'}

[정책 목록]
{policy_text}

출력 규칙:
1. "탈락사유"는 아래 규칙을 엄격히 따른다:
   ① "미충족조건(필수탈락)"이 있으면 → 해당 조건을 구체적으로 서술 (예: "연소득 기준 초과: 사용자 소득 3,200만원이 기준 2,400만원을 초과합니다.")
   ② "잠재리스크(소프트경고)"가 있으면 → 해당 리스크를 이 정책 고유의 맥락으로 서술 (예: "나이 상한 임박: 만 34세 이하 조건에서 사용자는 현재 33세로 내년 신청 불가.")
   ③ 미충족조건도 없고 소프트경고도 없으면 → "탈락사유": [] 로 빈 배열 반환. 절대 임의로 채우지 말 것.
   ④ 금지사항: "서류 미비 가능성", "행정 처리 지연", "서류를 미리 준비하지 않으면 지연될 수 있습니다" 같은
      모든 정책에 공통으로 적용 가능한 일반적·절차적 문구는 절대 사용하지 말 것.
   각 항목: {{"icon": "이모지", "html": "<strong>제목:</strong> 설명 문장 (최대 60자)"}}

2. "해결방법"은 "탈락사유" 각 항목에 1:1 대응하는 구체적 행동 가이드로 구성한다.
   - 탈락사유가 빈 배열이면 → 신청 절차 중심의 긍정적 액션 가이드 3단계로 대체
   - 각 단계는 이 정책에서만 유효한 구체적 행동이어야 함 (예: 기관명, 신청처, 조건 수치 포함)
   - 금지사항: "필요한 서류를 준비합니다", "서류를 제출하고 신청합니다" 같은 모든 정책에 공통인 문구 금지
   형식: {{"icon": "이모지", "html": "<strong>N단계: 제목</strong> — 설명 문장"}}
   아이콘 예: ✅ 확인, 📎 서류, 🚀 신청, 📝 작성, 🏛️ 기관, 🔍 조회, 💡 팁, 📅 기한

3. "icon"은 정책 성격 이모지 1개 (예: 🏠 💰 🎓 💼 🏥 📋).
4. "subtitle"은 한 줄 조건 요약 (예: 만 19~34세 · 월세 60만원 이하).
5. "benefit_label"은 혜택 요약 (예: 연 240만원, 최대 500만원).
6. "수급확률"은 0~100 정수. rule-based 값을 기반으로 소프트경고 수에 따라 ±5 조정 가능.
7. "개인요약"은 아래 4가지를 모두 포함한 2~3문장:
   ① 핵심 자격 조건 (충족/미충족 명시)
   ② 예상 혜택 금액 또는 내용
   ③ 신청 난이도 또는 우선순위
   ④ 주요 리스크 한 줄 (탈락사유 중 가장 중요한 것)
8. "policy_id" slug 규칙:
   - 한글·영문·숫자 외 모든 문자 → 하이픈(-)
   - 영문 소문자 변환, 연속 하이픈 → 하나, 앞뒤 하이픈 제거
   예) "청년 월세 한시 특별지원" → "청년-월세-한시-특별지원"

아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "포트폴리오": [
    {{
      "policy_id": "slug-형식",
      "서비스명": "정책명",
      "icon": "🏠",
      "subtitle": "한 줄 조건 요약",
      "benefit_label": "혜택 요약",
      "source_label": "출처기관 약칭",
      "수급확률": 85,
      "개인요약": "...",
      "탈락사유": [
        {{"icon": "⚠️", "html": "<strong>제목:</strong> 설명 문장."}},
        {{"icon": "📋", "html": "<strong>제목:</strong> 설명 문장."}}
      ],
      "해결방법": [
        {{"icon": "✅", "html": "<strong>1단계: 제목</strong> — 설명 문장."}},
        {{"icon": "📎", "html": "<strong>2단계: 제목</strong> — 설명 문장."}},
        {{"icon": "🚀", "html": "<strong>3단계: 제목</strong> — 설명 문장."}}
      ],
      "우선순위": 1,
      "중복수급주의": false
    }}
  ],
  "종합요약": "복지 포트폴리오 전체 요약 (2~3문장)",
  "대시보드통계": {{
    "해당정책수": 12,
    "평균확률": 87,
    "예상수혜액": "1,040만",
    "즉시신청가능": 3
  }}
}}
"""

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    raw = resp.choices[0].message.content
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("JSON 파싱 실패: %s\n원문: %s", e, raw[:200])
        return {
            "포트폴리오": [],
            "종합요약": "분석 결과를 파싱하는 중 오류가 발생했습니다.",
            "대시보드통계": {},
        }


# ── 2. HTML 렌더링용 구조 후처리 ─────────────────────────────
def _enrich_for_html(result: dict) -> dict:
    """
    GPT 응답에 CSS 클래스 정보 추가 + 탈락사유/해결방법 정규화.
    policy_id를 _make_slug()로 재계산해 main.py gpt_map 키와 일치시킴.
    """
    enriched = []
    for i, item in enumerate(result.get("포트폴리오", [])):
        service_name    = item.get("서비스명", "")
        item["policy_id"] = _make_slug(service_name, i)

        score = item.get("수급확률", 0)
        css   = _score_to_css(score)

        issue_icons = ["⚠️", "📋", "🔎", "📌", "❗"]
        raw_issues  = item.get("탈락사유", [])
        issues = []
        for j, x in enumerate(raw_issues):
            if isinstance(x, str):
                issues.append({"icon": issue_icons[j % len(issue_icons)], "html": x})
            else:
                issues.append(x)

        guide_icons = ["✅", "📎", "🚀", "📝"]
        raw_guides  = item.get("해결방법", [])
        guides = []
        for j, x in enumerate(raw_guides):
            if isinstance(x, str):
                guides.append({"icon": guide_icons[j % len(guide_icons)], "html": x})
            else:
                guides.append(x)

        enriched.append({
            **item,
            "_css":   css,
            "탈락사유": issues,
            "해결방법": guides,
        })

    result["포트폴리오"] = enriched
    return result


# ── 3. 터미널 출력 ────────────────────────────────────────────
def _print_result(result: dict) -> None:
    portfolio = result.get("포트폴리오", [])
    summary   = result.get("종합요약", "")

    print()
    print("=" * 60)
    print("  베네픽 — 복지 분석 결과")
    print("=" * 60)
    print(f"\n📋 종합 요약\n{summary}\n")

    for item in portfolio:
        score     = item.get("수급확률", 0)
        name      = item.get("서비스명", "")
        failures  = item.get("탈락사유", [])
        solutions = item.get("해결방법", [])
        priority  = item.get("우선순위", 0)
        duplicate = item.get("중복수급주의", False)
        css       = item.get("_css", {})

        emoji = {"top": "✅", "mid": "🔶", "low": "❌"}.get(css.get("card_class", "low"), "❌")

        print(f"{'─' * 60}")
        print(f"{emoji}  [{score}%] {name}  (우선순위 {priority}위)")
        if duplicate:
            print("  ⚠️  중복수급 주의")

        personal_summary = item.get("개인요약", "")
        if personal_summary:
            print(f"\n  📄 원문 발췌\n  {personal_summary}")

        if failures:
            print("\n  ❌ 탈락 예상 이유")
            for f in failures:
                html  = f.get("html", f) if isinstance(f, dict) else f
                clean = re.sub(r"<[^>]+>", "", html)
                icon  = f.get("icon", "•") if isinstance(f, dict) else "•"
                print(f"    {icon} {clean}")
        else:
            print("\n  ❌ 탈락 예상 이유")
            print("    ✅ 탈락 사유 없음 — 조건 충족")

        if solutions:
            print("\n  💡 해결 방법 & 행동 가이드")
            for s in solutions:
                html  = s.get("html", s) if isinstance(s, dict) else s
                clean = re.sub(r"<[^>]+>", "", html)
                icon  = s.get("icon", "▸") if isinstance(s, dict) else "▸"
                print(f"    {icon} {clean}")

    stats = result.get("대시보드통계", {})
    if stats:
        print(f"\n{'─' * 60}")
        print(f"  📊 대시보드 통계")
        print(f"    해당 정책 수: {stats.get('해당정책수', '-')}건")
        print(f"    평균 확률:    {stats.get('평균확률', '-')}%")
        print(f"    예상 수혜액:  {stats.get('예상수혜액', '-')}원")
        print(f"    즉시 신청:    {stats.get('즉시신청가능', '-')}건")
    print(f"{'─' * 60}\n")


# ── 4. 공개 인터페이스 ────────────────────────────────────────
def analyze(user: dict, policies: list[dict]) -> dict:
    """
    사용자 정보 + 스코어링된 정책 → GPT 분석 → HTML 렌더링용 dict 반환
    """
    log.info("GPT-4o mini 분석 시작...")
    try:
        result = _call_gpt(user, policies)
    except EnvironmentError as e:
        print(f"\n⚠️  설정 오류: {e}\n")
        return {}
    except Exception as e:
        log.error("GPT 호출 실패: %s", e)
        print(f"\n⚠️  GPT 분석 실패: {e}\n")
        return {}

    result = _enrich_for_html(result)
    _print_result(result)
    return result


# ── 5. 단독 실행 ──────────────────────────────────────────────
if __name__ == "__main__":
    from user_input import get_user_input
    from policy_search import search_policies
    from scoring import score_policies

    user     = get_user_input()
    policies = search_policies(user, top_k=10)
    scored   = score_policies(user, policies)
    analyze(user, scored)
