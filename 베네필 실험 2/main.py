"""
베네픽(Benefic) FastAPI 서버
============================
API 명세 초안의 4개 엔드포인트 구현:
  POST /analyze
  GET  /policy/{policy_id}/detail
  GET  /portfolio/{query_id}
  GET  /apply-assist/{policy_id}

실행:
  pip install fastapi uvicorn python-dotenv openai faiss-cpu sentence-transformers
  uvicorn main:app --reload --port 8000

환경변수:
  OPENAI_API_KEY=sk-...   (.env 파일 또는 셸 환경)
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from dotenv import load_dotenv
load_dotenv()

# 프로젝트 내 모듈 (같은 디렉터리에 위치해야 함)
from scoring import score_policies
from policy_search import search_policies
from analysis import analyze  # GPT 분석 (탈락사유/해결방법 생성)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("benefic.api")

app = FastAPI(
    title="베네픽 API",
    description="복지 수급 가능성 분석 서비스 REST API",
    version="2.0.0",
)

# CORS — HTML 파일을 로컬에서 file:// 로 열거나 다른 포트에서 접근할 때 필요
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 인메모리 세션 저장소 ──────────────────────────────────────
# 실제 서비스에서는 Redis / DB로 교체하세요.
_sessions: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────
# 공통 에러 응답 헬퍼
# ─────────────────────────────────────────────────────────────
def _err(code: str, msg: str, status: int):
    raise HTTPException(status_code=status, detail={"error_code": code, "message": msg})


# ─────────────────────────────────────────────────────────────
# 1. POST /analyze
# ─────────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    user_name:         str
    age:               int
    region:            str
    income_percent:    int             # 중위소득 비율 (%)
    household_type:    str
    employment_status: str
    education_level:   Optional[str] = None
    language:          Optional[str] = "ko"

    # 선택 필드 (scoring.py 조건 파싱에 필요)
    household_size:    Optional[int]  = 1
    disability:        Optional[str]  = "없음"
    veteran:           Optional[bool] = False
    multicultural:     Optional[bool] = False


@app.post("/analyze")
async def post_analyze(req: AnalyzeRequest):
    """
    사용자 조건 입력 → 정책 검색 → 스코어링 → GPT 분석 → 대시보드 데이터 반환
    """
    # ── 1) income_percent → 연소득 만원 환산 ─────────────────
    # 중위소득 기준: 1인 가구 월 222만원 × 12 = 2,664만원 (2024)
    MEDIAN_ANNUAL = {1: 2664, 2: 4416, 3: 5652, 4: 6864, 5: 8028, 6: 9132}
    median = MEDIAN_ANNUAL.get(req.household_size or 1, 2664)
    annual_income = round(median * req.income_percent / 100)

    # ── 2) scoring.py 호환 user dict 구성 ────────────────────
    user = {
        "나이":       req.age,
        "연소득":     annual_income,
        "가구유형":   req.household_type,
        "가구원수":   req.household_size or 1,
        "거주지역":   req.region,
        "고용상태":   req.employment_status,
        "장애여부":   req.disability or "없음",
        "국가유공자": req.veteran or False,
        "다문화가구": req.multicultural or False,
    }

    # ── 3) 정책 검색 + 스코어링 ──────────────────────────────
    try:
        policies = search_policies(user, top_k=10)
        scored   = score_policies(user, policies)
    except FileNotFoundError as e:
        _err("INDEX_NOT_FOUND", str(e), 503)
    except Exception as e:
        log.error("검색/스코어링 오류: %s", e)
        _err("SEARCH_ERROR", f"정책 검색 중 오류: {e}", 500)

    # ── 5) GPT 분석 (analysis.py) — 탈락사유·해결방법 보강 ────
    gpt_result = {}
    try:
        gpt_result = analyze(user, scored) or {}
    except Exception as e:
        log.warning("GPT 분석 스킵 (오류): %s", e)

    # GPT 포트폴리오 결과를 policy_id 기준으로 인덱싱
    gpt_map: dict[str, dict] = {}
    for item in gpt_result.get("포트폴리오", []):
        gpt_map[item.get("policy_id", "")] = item

    # ── 6) scoring.py 결과 → 카드 데이터 변환 ───────────────
    # GPT 분석 없이 scoring.py 결과를 직접 사용
    def _score_to_css(score_float: float) -> dict:
        pct = round(score_float * 100)
        if pct >= 80:
            return {"card_class": "top",  "percent_class": "high", "progress_color": "green",
                    "icon_color": "green",  "badge_class": "badge-green",  "badge_label": "✅ 조건 충족"}
        elif pct >= 60:
            return {"card_class": "mid",  "percent_class": "mid",  "progress_color": "blue",
                    "icon_color": "blue",   "badge_class": "badge-blue",   "badge_label": "⚡ 확인 필요"}
        else:
            return {"card_class": "low",  "percent_class": "low",  "progress_color": "orange",
                    "icon_color": "orange", "badge_class": "badge-orange", "badge_label": "⚠️ 조건 부족"}

    ICON_MAP = {"현금": "💰", "서비스": "🛎️", "교육": "🎓", "주거": "🏠",
                "취업": "💼", "의료": "🏥", "돌봄": "👶", "금융": "🏦"}

    def _pick_icon(p: dict) -> str:
        category = p.get("서비스분야") or p.get("지원유형") or ""
        for kw, icon in ICON_MAP.items():
            if kw in category:
                return icon
        return "📋"

    def _make_slug(name: str, idx: int) -> str:
        import re
        # 한글·영문·숫자 외 모두 하이픈으로 교체, 연속 하이픈 정리
        slug = re.sub(r"[^\w가-힣]", "-", name).strip("-").lower()
        slug = re.sub(r"-+", "-", slug)
        return slug or f"policy-{idx}"

    def _extract_benefit(p: dict) -> str:
        """
        지원내용에서 금액을 추출해 카드 benefit_label로 반환.
        패턴 예시: 100,000원 / 월 20만원 / 최대 500만원 / 연 240만원
        수정: "월 N만원 × 최대 M개월" 총액 계산 + 가장 큰 금액 우선 선택
        """
        import re

        text = str(p.get("지원내용") or p.get("서비스목적요약") or "")

        # 1순위: "월 N만원 × 최대 M개월" → 총액 계산 (예: 월 50만원 × 최대 6개월 → 최대 300만원)
        m = re.search(r"월\s*([\d,]+)\s*만\s*원?\s*[×x]\s*최대\s*(\d+)\s*개월", text)
        if m:
            monthly = int(m.group(1).replace(",", ""))
            months  = int(m.group(2))
            return f"최대 {monthly * months:,}만원"

        # 2순위: "최대/월/연/1인당/가구당 + N만원" 패턴 → 여러 개 중 가장 큰 값
        candidates = re.findall(r"(최대|월|연|1인당|가구당)?\s*([\d,]+)\s*만\s*원", text)
        if candidates:
            best_val, best_str = 0, ""
            for prefix, num_str in candidates:
                val = int(num_str.replace(",", ""))
                if val > best_val:
                    best_val = val
                    label = prefix.strip()
                    best_str = f"{label} {val:,}만원".strip() if label else f"{val:,}만원"
            if best_str:
                # 띄어쓰기 정규화
                return re.sub(r"만\s+원", "만원", best_str)

        # 3순위: 숫자,숫자 + 원 패턴 → 가장 큰 값 만원 환산
        amounts = re.findall(r"([\d,]+)\s*원", text)
        if amounts:
            try:
                vals = [int(a.replace(",", "")) for a in amounts]
                max_val = max(vals)
                if max_val >= 10000:
                    return f"최대 {max_val // 10000:,}만원"
                else:
                    return f"최대 {max_val:,}원"
            except Exception:
                pass

        # 4순위: 억원 패턴
        m = re.search(r"[\d,]+\s*억\s*원?", text)
        if m:
            return m.group(0).strip()

        # fallback: 지원유형
        return p.get("지원유형") or "-"

    # scored 전체를 카드로 변환 (score 내림차순 이미 정렬됨)
    all_cards = []
    seen_slugs = set()  # policy_id 중복 제거
    for i, p in enumerate(scored):
        pct = round(p.get("score", 0) * 100)
        css = _score_to_css(p.get("score", 0))
        institution = p.get("소관기관명", "Gov24") or "Gov24"
        # subtitle: 지원대상 앞 50자
        target_raw = (p.get("지원대상") or p.get("선정기준") or "")
        subtitle = target_raw[:50].replace("\n", " ") if target_raw else "조건 확인 필요"

        slug = _make_slug(p.get("서비스명", ""), i)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        gpt  = gpt_map.get(slug, {})

        # GPT 탈락사유/해결방법: _enrich_for_html 이후 [{icon, html}, ...] 객체 배열
        # 키 이름은 한글("탈락사유"/"해결방법")이므로 그대로 사용
        all_cards.append({
            "policy_id":           slug,
            "icon":                gpt.get("icon") or _pick_icon(p),
            "policy_name":         p.get("서비스명", "-"),
            "subtitle":            gpt.get("subtitle") or subtitle,
            "benefit_label":       gpt.get("benefit_label") or _extract_benefit(p),
            "source_label":        institution[:6],
            "eligibility_percent": gpt.get("수급확률") or pct,
            "_css":                gpt.get("_css") or css,           # GPT CSS 우선
            "_matched":            p.get("matched", []),
            "_failed":             p.get("failed", []),
            "_issues":             gpt.get("탈락사유", []),          # [{icon, html}, ...]
            "_guides":             gpt.get("해결방법", []),          # [{icon, html}, ...]
            "_raw":                p,
        })

    # ── 5) query_id 발급 + 세션 저장 ─────────────────────────
    today    = datetime.now().strftime("%Y%m%d")
    query_id = f"query_{today}_{uuid.uuid4().hex[:8]}"

    _sessions[query_id] = {
        "user":      user,
        "user_name": req.user_name,
        "scored":    scored,
        "all_cards": all_cards,
        "created_at": datetime.now().isoformat(),
    }

    # ── 6) 응답 조립 ─────────────────────────────────────────
    income_label = f"중위소득 {req.income_percent}%"
    now_label    = datetime.now().strftime("오늘 오전 %I:%M").replace(" 0", " ")

    passed       = [c for c in all_cards if c["eligibility_percent"] >= 60]
    avg_pct      = round(sum(c["eligibility_percent"] for c in all_cards) / len(all_cards)) if all_cards else 0
    ready_count  = sum(1 for c in all_cards if c["eligibility_percent"] >= 80)

    portfolio_preview_items = [
        {"icon": c["icon"], "label": c["policy_name"], "benefit_label": c["benefit_label"]}
        for c in all_cards[:4]
    ]

    return {
        "query_id": query_id,
        "cards": all_cards,          # HTML이 직접 참조하는 카드 목록
        "dashboard_data": {
            "user_profile": {
                "user_name":        req.user_name,
                "updated_at_label": now_label,
                "region_label":     req.region,
                "total_score":      avg_pct,
                "score_max":        100,
                "tags": [
                    f"📅 만 {req.age}세",
                    f"📍 {req.region}",
                    f"💰 {income_label}",
                    f"🏠 {req.household_type}",
                    f"👔 {req.employment_status}",
                    *([ f"♿ {req.disability}"] if req.disability and req.disability != "없음" else []),
                ],
            },
            "condition_form": {
                "current_values": {
                    "age_label":         f"만 {req.age}세",
                    "region":            req.region,
                    "income_label":      income_label,
                    "household_type":    req.household_type,
                    "employment_status": req.employment_status,
                    "education_level":   req.education_level or "",
                }
            },
            "recommendation_cards": all_cards,   # 전체 전달 (HTML에서 상위 N개 렌더링)
            "dashboard_stats": {
                "matched_policy_count":         len(all_cards),
                "average_probability_percent":  avg_pct,
                "expected_total_benefit_label": "-",
                "ready_apply_count":            ready_count,
            },
            "portfolio_preview": {
                "total_expected_benefit_label": "-",
                "items": portfolio_preview_items,
            },
            "summary": f"총 {len(all_cards)}개 정책 분석 완료. 수급 가능(60% 이상) {len(passed)}건.",
        },
    }


# ─────────────────────────────────────────────────────────────
# 2. GET /policy/{policy_id}/detail
# ─────────────────────────────────────────────────────────────
@app.get("/policy/{policy_id}/detail")
async def get_policy_detail(
    policy_id: str,
    query_id: str = Query(..., description="분석 세션 식별자"),
):
    """
    특정 정책의 상세 분석 — scoring.py matched/failed 기반으로 반환
    """
    session = _sessions.get(query_id)
    if not session:
        _err("SESSION_NOT_FOUND", "분석 세션을 찾을 수 없습니다. 먼저 POST /analyze를 호출하세요.", 404)

    all_cards = session.get("all_cards", [])
    card = next((c for c in all_cards if c.get("policy_id") == policy_id), None)
    if not card:
        _err("POLICY_NOT_FOUND", f"policy_id={policy_id} 에 해당하는 정책을 찾을 수 없습니다.", 404)

    css     = card.get("_css", {})
    matched = card.get("_matched", [])
    failed  = card.get("_failed", [])
    raw     = card.get("_raw", {})

    # ── issue-item 구성 ──────────────────────────────────────
    # 우선순위: GPT 탈락사유(_issues) > rule-based _failed > 기본 메시지
    issue_icons = ["⚠️", "📋", "🔎", "📌", "❗"]
    issues = []

    gpt_issues = card.get("_issues", [])   # analysis.py GPT 결과 [{icon, html}, ...] 객체 배열
    if gpt_issues:
        for i, item in enumerate(gpt_issues):
            # item이 dict({icon, html})이면 .html 꺼내고, 문자열이면 그대로 사용
            if isinstance(item, dict):
                icon_str = item.get("icon", issue_icons[i % len(issue_icons)])
                html_str = item.get("html", str(item))
            else:
                icon_str = issue_icons[i % len(issue_icons)]
                html_str = str(item)
            issues.append({
                "issue_id": f"issue_{i+1}",
                "icon":     icon_str,
                "html":     html_str,
            })
    elif failed:
        # GPT 분석 없을 때 rule-based 미충족 조건으로 fallback
        for i, f in enumerate(failed):
            issues.append({
                "issue_id": f"issue_{i+1}",
                "icon":     issue_icons[i % len(issue_icons)],
                "html":     f"<strong>미충족 조건:</strong> {f}",
            })
    else:
        issues.append({
            "issue_id": "issue_1",
            "icon":     "✅",
            "html":     "<strong>탈락 요인 없음:</strong> 현재 조건상 주요 자격 요건을 모두 충족합니다. 서류 미비 등 잠재 리스크에 유의하세요.",
        })

    # ── guide-item 구성 ──────────────────────────────────────
    # 우선순위: GPT 해결방법(_guides) > rule-based 신청 정보
    guide_icons  = ["✅", "📎", "🚀", "📝"]
    guides = []

    gpt_guides = card.get("_guides", [])   # analysis.py GPT 결과 [{icon, html}, ...] 객체 배열
    if gpt_guides:
        for i, item in enumerate(gpt_guides):
            if isinstance(item, dict):
                icon_str = item.get("icon", guide_icons[i % len(guide_icons)])
                html_str = item.get("html", str(item))
            else:
                icon_str = guide_icons[i % len(guide_icons)]
                html_str = str(item)
            guides.append({
                "step": i + 1,
                "icon": icon_str,
                "html": html_str,
            })
    else:
        # GPT 분석 없을 때 raw 정책 데이터로 rule-based fallback
        apply_method = raw.get("신청방법") or "정부24(gov.kr) 또는 관할 주민센터 방문"
        reception    = raw.get("접수기관") or raw.get("소관기관명") or "-"
        deadline     = raw.get("신청기한") or "상시"
        phone        = raw.get("전화문의") or "-"
        url          = raw.get("상세조회url") or "https://www.bokjiro.go.kr"

        guides = [
            {"step": 1, "icon": guide_icons[0],
             "html": f"<strong>1단계: 충족 조건 확인</strong> — {', '.join(matched) if matched else '해당 없음'}"},
            {"step": 2, "icon": guide_icons[1],
             "html": f"<strong>2단계: 신청 방법</strong> — {apply_method}"},
            {"step": 3, "icon": guide_icons[2],
             "html": f"<strong>3단계: 접수 기관 및 기한</strong> — {reception} / 신청기한: {deadline}"},
            {"step": 4, "icon": guide_icons[3],
             "html": f"<strong>4단계: 문의 및 상세 정보</strong> — 전화: {phone} / <a href='{url}' target='_blank' style='color:var(--blue)'>상세 페이지 →</a>"},
        ]

    return {
        "detail_data": {
            "policy_header": {
                "policy_id":           policy_id,
                "icon":                card.get("icon", "📋"),
                "policy_name":         card.get("policy_name", ""),
                "eligibility_percent": card.get("eligibility_percent", 0),
                "progress_color":      css.get("progress_color", "blue"),
                "card_class":          css.get("card_class", "mid"),
                "badge_label":         css.get("badge_label", ""),
            },
            "issues":  issues,
            "guides":  guides,
            "summary_stats": {
                "benefit_label":           card.get("benefit_label", "-"),
                "processing_period_label": "1~2개월",
                "issue_count":             len(failed),
                "source_label":            card.get("source_label", "Gov24"),
            },
            "actions": {
                "apply_assist_enabled":      True,
                "back_to_dashboard_enabled": True,
            },
        }
    }


# ─────────────────────────────────────────────────────────────
# 3. GET /portfolio/{query_id}
# ─────────────────────────────────────────────────────────────
@app.get("/portfolio/{query_id}")
async def get_portfolio(query_id: str):
    """
    분석 세션 기준 최적 정책 포트폴리오 반환
    """
    session = _sessions.get(query_id)
    if not session:
        _err("PORTFOLIO_NOT_FOUND", "해당 분석 세션의 포트폴리오 결과가 없습니다.", 404)

    all_cards = session.get("all_cards", [])
    user_name = session.get("user_name", "사용자")

    ready_count       = sum(1 for c in all_cards if c["eligibility_percent"] >= 80)
    conditional_count = sum(1 for c in all_cards if 60 <= c["eligibility_percent"] < 80)

    # ── 총 예상 수혜액 계산 ──────────────────────────────────
    import re as _re
    total_wan = 0
    for c in all_cards:
        if c["eligibility_percent"] < 60:
            continue
        label = c.get("benefit_label", "") or ""
        # "연 240만원", "최대 500만원", "240만원" 등에서 숫자 추출
        m = _re.search(r"([\d,]+)\s*만", label)
        if m:
            try:
                total_wan += int(m.group(1).replace(",", ""))
            except Exception:
                pass

    if total_wan >= 10000:
        total_label = f"{total_wan // 10000}억 {total_wan % 10000:,}만원" if total_wan % 10000 else f"{total_wan // 10000}억원"
    elif total_wan > 0:
        total_label = f"{total_wan:,}만원"
    else:
        total_label = "-"

    # ── 카드 목록 구성 ────────────────────────────────────────
    items = []
    for c in all_cards:
        score = c["eligibility_percent"]
        if score >= 80:
            status = "ready"
        elif score >= 60:
            status = "conditional"
        else:
            status = "blocked"

        # benefit_period_label: subtitle에서 기간/조건 요약 추출
        subtitle = c.get("subtitle", "") or ""
        # subtitle 앞부분(나이·조건)을 기간 레이블로 활용
        period_label = subtitle[:30] if subtitle else "-"

        items.append({
            "policy_id":              c.get("policy_id", ""),
            "icon":                   c.get("icon", "📋"),
            "policy_name":            c.get("policy_name", ""),
            "expected_benefit_label": c.get("benefit_label", "-"),
            "benefit_period_label":   period_label,
            "status":                 status,
            "eligibility_percent":    score,
            "_css":                   c.get("_css", {}),
        })

    return {
        "portfolio_data": {
            "portfolio_hero": {
                "total_expected_benefit_label": total_label,
                "portfolio_basis_label":        f"{len(all_cards)}개 정책 기준 · {user_name}님 맞춤 분석",
                "ready_count":                  ready_count,
                "conditional_count":            conditional_count,
            },
            "portfolio_items": items,
            "portfolio_cta": {
                "headline":             "🚀 이 조합으로 지금 바로 신청하세요!",
                "description":          f"총 {len(all_cards)}개 정책 혜택을 한 번에 챙길 수 있어요",
                "apply_assist_enabled": True,
            },
        }
    }


# ─────────────────────────────────────────────────────────────
# 4. GET /apply-assist/{policy_id}
# ─────────────────────────────────────────────────────────────

# 정책별 필요 서류 템플릿 (실제 서비스에서는 DB에서 로드)
_DOCUMENT_TEMPLATES: dict[str, list[dict]] = {
    "default": [
        {"doc_id": "resident_cert",  "icon": "🪪", "name": "주민등록등본",   "description": "3개월 이내 발급"},
        {"doc_id": "income_cert",    "icon": "💳", "name": "소득 확인서",     "description": "건강보험료 납부확인서"},
        {"doc_id": "bank_account",   "icon": "🏦", "name": "통장 사본",       "description": "본인 명의 계좌"},
    ],
    "youth-rent": [
        {"doc_id": "resident_cert",  "icon": "🪪", "name": "주민등록등본",   "description": "3개월 이내"},
        {"doc_id": "lease_contract", "icon": "📄", "name": "임대차 계약서",   "description": "확정일자 포함"},
        {"doc_id": "income_cert",    "icon": "💳", "name": "소득 확인서",     "description": "건강보험료 납부확인서"},
        {"doc_id": "bank_account",   "icon": "🏦", "name": "통장 사본",       "description": "월세 입금 계좌"},
    ],
}

@app.get("/apply-assist/{policy_id}")
async def get_apply_assist(
    policy_id: str,
    query_id: Optional[str] = Query(None, description="분석 세션 식별자 (선택)"),
):
    """
    신청 단계, 필요 서류, 체크리스트, 신청 링크 반환
    """
    # 정책 기본 정보 조회 (세션이 있으면 우선 사용)
    policy_name = policy_id
    apply_url   = "https://www.bokjiro.go.kr"
    source_label = "Gov24"

    if query_id and query_id in _sessions:
        portfolio = _sessions[query_id]["result"].get("포트폴리오", [])
        found = next(
            (p for p in portfolio if p.get("policy_id") == policy_id),
            None,
        )
        if found:
            policy_name  = found.get("서비스명", policy_id)
            source_label = found.get("source_label", "Gov24")

    # 필요 서류
    docs_template = _DOCUMENT_TEMPLATES.get(policy_id, _DOCUMENT_TEMPLATES["default"])
    document_cards = []
    for doc in docs_template:
        # 기본적으로 첫 번째 서류는 '준비 완료', 나머지는 '준비 필요' (데모용)
        status = "ready" if doc["doc_id"] == "resident_cert" else "missing"
        document_cards.append({
            **doc,
            "status":       status,
            "status_label": "준비 완료" if status == "ready" else "준비 필요",
        })

    checklist = [
        {"item_id": "input_done",    "label": "신청자 기본 정보 입력 완료", "done": True},
        {"item_id": "analysis_done", "label": "AI 수급 가능성 분석 완료",   "done": True},
        {"item_id": "doc_review",    "label": "필요 서류 목록 확인",         "done": True},
        {"item_id": "doc_upload",    "label": "서류 업로드 / 원본 준비",     "done": False},
        {"item_id": "apply_submit",  "label": "온라인 신청서 제출",          "done": False},
    ]

    return {
        "apply_assist_data": {
            "flow_steps": [
                {"step": 1, "label": "정보 입력",  "status": "done"},
                {"step": 2, "label": "AI 분석",    "status": "done"},
                {"step": 3, "label": "원인 파악",  "status": "done"},
                {"step": 4, "label": "서류 준비",  "status": "active"},
                {"step": 5, "label": "신청 완료",  "status": "todo"},
            ],
            "document_cards": document_cards,
            "checklist":      checklist,
            "apply_meta": {
                "policy_name":  policy_name,
                "apply_url":    apply_url,
                "source_label": source_label,
            },
        }
    }


# ─────────────────────────────────────────────────────────────
# 헬스체크
# ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(_sessions)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
