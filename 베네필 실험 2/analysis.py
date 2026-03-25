"""
08 탈락 사유 분석 + 09 복지 포트폴리오 추천 + 10 요약 생성
============================================================
수정: HTML policy-card / issue-item / guide-item 클래스 구조에 맞는
      JSON 스키마 출력 추가 (기존 터미널 출력 병행 유지)
"""

from __future__ import annotations

import json
import os
import logging

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

log = logging.getLogger("benefic.analysis")

MODEL = "gpt-4o-mini"

# ── CSS 클래스 매핑 ──────────────────────────────────────────
# score → HTML policy-card 의 tone 클래스 + percent-num 색상 클래스
def _score_to_css(score: int) -> dict:
    """
    수급 확률 → HTML 렌더링에 필요한 CSS 클래스명 반환
    policy-card:   top(≥80) / mid(≥60) / low(<60)
    percent-num:   high / mid / low
    progress-fill: green / blue / orange
    policy-icon:   green / blue / orange
    badge:         badge-green / badge-blue / badge-orange
    """
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
    top_policies = policies[:5]

    policy_text = ""
    for i, p in enumerate(top_policies, 1):
        policy_text += f"""
[정책 {i}]
- 서비스명: {p.get('서비스명', '-')}
- 지원유형: {p.get('지원유형', '-')}
- 지원대상: {p.get('지원대상', p.get('소관기관명', '-'))}
- 수급확률(rule-based): {int(p.get('score', 0) * 100)}%
- 충족조건: {', '.join(p.get('matched', [])) or '없음'}
- 미충족조건: {', '.join(p.get('failed', [])) or '없음'}
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
1. "탈락사유"는 각 항목이 {{"icon": "이모지", "html": "HTML 문자열"}} 객체.
   html은 <div class="issue-item"> 안의 <p>에 들어갈 짧고 명확한 문장.
   <strong>제목:</strong> 설명 형식으로 작성. 최대 60자 이내.
   icon은 내용에 맞는 이모지 (예: ⚠️ 서류, 📋 기준 미달, 🔎 확인 필요, 📌 기간, ❗ 중요).
2. "해결방법"은 각 항목이 {{"icon": "이모지", "html": "HTML 문자열"}} 객체.
   html은 <div class="guide-item"> 안의 <p>에 들어갈 구체적 행동 가이드.
   <strong>N단계: 제목</strong> — 설명 형식. 3단계 이상 필수.
   icon은 단계 성격에 맞는 이모지 (예: ✅ 확인, 📎 서류, 🚀 신청, 📝 작성, 🏛️ 기관).
3. "icon"은 정책 성격에 맞는 이모지 1개 (예: 🏠 💰 🎓 💼 🏥 📋).
4. "subtitle"은 policy-card의 <p>에 들어갈 한 줄 조건 요약 (예: 만 19~34세 · 월세 60만원 이하).
5. "benefit_label"은 benefit-chip에 들어갈 혜택 요약 (예: 연 240만원, 최대 500만원).
6. 탈락사유·해결방법은 절대 빈 배열 금지. 수급확률이 높아도 잠재 리스크 포함.
7. "수급확률"은 0~100 정수.
8. "policy_id"는 반드시 서비스명을 한글 그대로 소문자 변환 후 특수문자를 하이픈(-)으로 교체한 slug.
   예) "청년 월세 한시 특별지원" → "청년-월세-한시-특별지원"
   공백은 하이픈으로, 괄호/점/슬래시 등 특수문자도 하이픈으로. 앞뒤 하이픈 제거.

아래 JSON 형식으로만 응답 (다른 텍스트 없이):
{{
  "포트폴리오": [
    {{
      "policy_id": "slug-형식-영문소문자",
      "서비스명": "정책명",
      "icon": "🏠",
      "subtitle": "한 줄 조건 요약",
      "benefit_label": "혜택 요약",
      "source_label": "출처기관 약칭",
      "수급확률": 85,
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
  "종합요약": "사용자에게 맞는 복지 포트폴리오 전체 요약 (2~3문장)",
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
        return {"포트폴리오": [], "종합요약": "분석 결과를 파싱하는 중 오류가 발생했습니다.", "대시보드통계": {}}


# ── 2. HTML 렌더링용 구조로 후처리 ───────────────────────────
def _enrich_for_html(result: dict) -> dict:
    """
    GPT 응답에 HTML 렌더링에 필요한 CSS 클래스 정보를 추가한다.
    각 policy 항목에 _css 키를 추가해 프론트엔드가 바로 사용할 수 있게 한다.

    탈락사유/해결방법 하위 호환:
      - 구버전(문자열 리스트): [{"icon":"⚠️","html":"..."}, ...] 로 자동 변환
      - 신버전(객체 리스트): 그대로 유지
    """
    enriched = []
    for item in result.get("포트폴리오", []):
        score = item.get("수급확률", 0)
        css = _score_to_css(score)

        # 탈락사유 정규화: 문자열이면 객체로 감쌈
        issue_icons = ["⚠️", "📋", "🔎", "📌", "❗"]
        raw_issues = item.get("탈락사유", [])
        issues = []
        for j, x in enumerate(raw_issues):
            if isinstance(x, str):
                issues.append({"icon": issue_icons[j % len(issue_icons)], "html": x})
            else:
                issues.append(x)

        # 해결방법 정규화: 문자열이면 객체로 감쌈
        guide_icons = ["✅", "📎", "🚀", "📝"]
        raw_guides = item.get("해결방법", [])
        guides = []
        for j, x in enumerate(raw_guides):
            if isinstance(x, str):
                guides.append({"icon": guide_icons[j % len(guide_icons)], "html": x})
            else:
                guides.append(x)

        enriched.append({**item, "_css": css, "탈락사유": issues, "해결방법": guides})

    result["포트폴리오"] = enriched
    return result


# ── 3. 터미널 출력 (기존 유지) ───────────────────────────────
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

        if failures:
            print("\n  ✕ 탈락 예상 이유 (issue-item)")
            for f in failures:
                # 신버전(객체) 또는 구버전(문자열) 모두 처리
                html = f.get("html", f) if isinstance(f, dict) else f
                clean = html.replace("<strong>", "").replace("</strong>", "")
                print(f"    • {clean}")

        if solutions:
            print("\n  💡 해결 방법 (guide-item)")
            for s in solutions:
                html = s.get("html", s) if isinstance(s, dict) else s
                clean = html.replace("<strong>", "").replace("</strong>", "")
                print(f"    {clean}")

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

    반환 구조:
    {
      "포트폴리오": [
        {
          "policy_id": "youth-rent",
          "서비스명": "청년 월세 한시 특별지원",
          "icon": "🏠",
          "subtitle": "만 19~34세 · 월세 60만원 이하",
          "benefit_label": "연 240만원",
          "source_label": "국토부",
          "수급확률": 92,
          "탈락사유": ["<strong>전입 미완료:</strong> ..."],
          "해결방법": ["<strong>1단계: ...</strong> — ..."],
          "우선순위": 1,
          "중복수급주의": false,
          "_css": {
            "card_class": "top",
            "percent_class": "high",
            "progress_color": "green",
            "icon_color": "green",
            "badge_class": "badge-green",
            "badge_label": "✅ 조건 충족"
          }
        }
      ],
      "종합요약": "...",
      "대시보드통계": {
        "해당정책수": 12,
        "평균확률": 87,
        "예상수혜액": "1,040만",
        "즉시신청가능": 3
      }
    }
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
