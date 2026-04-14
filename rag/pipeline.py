import os
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HF_CACHE_ROOT = PROJECT_ROOT / ".cache" / "huggingface"
os.environ.setdefault("HF_HOME", str(HF_CACHE_ROOT))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(HF_CACHE_ROOT / "sentence-transformers"))

try:
    from .searcher import HybridSearcher
except ImportError:
    from searcher import HybridSearcher
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from FlagEmbedding import FlagReranker

load_dotenv()

# ── 전역 초기화 ──
# searcher/reranker는 첫 검색 요청 시점에 로딩 (import 시 VRAM/RAM 충돌 방지)
_searcher = None
_reranker = None
llm = ChatOllama(
    model="gemma3:1b",
    temperature=0.3,
    num_predict=400,   # 최대 출력 토큰 제한 → 응답 30초 이내 보장
)

def get_searcher():
    global _searcher
    if _searcher is None:
        _searcher = HybridSearcher(device="cpu")
    return _searcher


def get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True, device='cuda')
    return _reranker

# ── 품질 기준 ──
QUALITY_HIGH   = 0.7
QUALITY_MEDIUM = 0.4


# ── 응답 형식 헬퍼 ──
def success_response(data: dict) -> dict:
    """팀 공통 성공 응답 형식"""
    return {
        "success": True,
        "data": data,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    }

def error_response(error_code: str, error_message: str) -> dict:
    """팀 공통 실패 응답 형식"""
    return {
        "success": False,
        "error_code": error_code,
        "error_message": error_message,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    }



# ── Reranking ──
def rerank(query: str, results: list, top_k: int = 5) -> list:
    """
    bge-reranker-v2-m3 로 정밀 재정렬
    score(float 0~1) 업데이트 후 반환
    """
    if not results:
        return []

    texts = [r['evidence_text'] for r in results]
    pairs = [[query, text] for text in texts]
    scores = get_reranker().compute_score(pairs, normalize=True)

    # score 업데이트 (팀 규칙: float 0~1)
    for result, score in zip(results, scores):
        result['score'] = round(float(score), 4)

    reranked = sorted(results, key=lambda x: x['score'], reverse=True)
    return reranked[:top_k]


# ── CRAG 품질 검증 ──
def crag_quality_check(query: str, results: list) -> list:
    """score 평균으로 품질 판단 후 3단계 분기"""
    if not results:
        return _fallback(query)

    # score는 float 0~1 사이 (팀 규칙)
    scores = [r['score'] for r in results]
    quality = sum(scores) / len(scores)
    print(f"[CRAG] 품질 점수: {quality:.3f}")

    if quality >= QUALITY_HIGH:
        print("[CRAG] 품질 양호 → 원본 결과 사용")
        return results

    elif quality >= QUALITY_MEDIUM:
        print("[CRAG] 품질 보통 → 조건 완화 재검색")
        relaxed = relax_query(query)
        results2 = get_searcher().search(relaxed, top_k=25, alpha=0.6)
        return rerank(query, results2, top_k=5)

    else:
        print("[CRAG] 품질 낮음 → 카테고리 폴백")
        return _fallback(query)


def relax_query(query: str) -> str:
    """지역/가구 수 같은 구체적 조건어 제거"""
    stopwords = [
        # 광역시/도
        '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
        '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
        # 구/군 단위 (뒤에 붙는 형태 제거)
        '강남구', '강북구', '강서구', '강동구', '관악구', '광진구', '구로구',
        '금천구', '노원구', '도봉구', '동대문구', '동작구', '마포구', '서대문구',
        '서초구', '성동구', '성북구', '송파구', '양천구', '영등포구', '용산구',
        '은평구', '종로구', '중구', '중랑구',
        # 가구/세대
        '1인', '2인', '3인', '4인', '가구', '세대',
        # 거주 표현
        '거주', '사는', '살고있는',
    ]
    relaxed = query
    for word in stopwords:
        relaxed = relaxed.replace(word, '').strip()
    relaxed = ' '.join(relaxed.split())
    print(f"[CRAG] 완화된 쿼리: '{query}' → '{relaxed}'")
    return relaxed


def get_category_query(query: str) -> str:
    """구체적 쿼리 → 상위 카테고리로 변환"""
    category_map = {
        '월세': '청년 주거 지원',
        '전세': '청년 주거 지원',
        '주거': '주거 지원',
        '취업': '청년 고용 지원',
        '실업': '청년 고용 지원',
        '실직': '고용 지원',
        '훈련비': '직업 훈련 지원',
        '훈련': '직업 훈련 지원',
        '생계': '저소득 생활 지원',
        '의료': '의료비 지원',
        '출산': '출산 육아 지원',
        '육아': '출산 육아 지원',
        '노인': '노인 복지 지원',
        '기초연금': '노인 복지 지원',
        '연금': '노인 복지 지원',
        '장애': '장애인 복지 지원',
        '긴급': '긴급복지 지원',
        '수급': '기초생활 지원',
    }
    for keyword, category in category_map.items():
        if keyword in query:
            return category
    return query


def _fallback(query: str) -> list:
    """상위 카테고리로 폴백 검색"""
    fallback_query = get_category_query(query)
    print(f"[CRAG] 폴백 쿼리: '{fallback_query}'")
    return get_searcher().search(fallback_query, top_k=5, alpha=0.6)


# ── LLM 답변 생성 ──
def generate_answer(query: str, docs: list, lang_code: str = "ko") -> str:
    """
    검색된 문서 기반 최종 답변 생성
    lang_code: "ko"/"en"/"vi"/"zh" (팀 규칙 — ISO 639-1)
    """
    context = "\n\n".join([
        f"[{i+1}] {d['policy_name']}\n{d['evidence_text']}"
        for i, d in enumerate(docs)
    ])

    lang_prompt = {
        "ko": "한국어로 답변하세요.",
        "en": "Please answer in English.",
        "vi": "Vui lòng trả lời bằng tiếng Việt.",
        "zh": "请用中文回答。",
    }.get(lang_code, "한국어로 답변하세요.")

    messages = [
        SystemMessage(content=f"""당신은 한국 복지 정책 추천 AI입니다.
주어진 문서를 바탕으로 사용자 질문에 답변하세요.
- 관련 정책명을 명확히 언급하세요
- 지원 대상, 지원 내용, 신청 방법을 간결하게 설명하세요
- 문서에 없는 내용은 추측하지 마세요
- {lang_prompt}"""),
        HumanMessage(content=f"질문: {query}\n\n참고 문서:\n{context}\n\n답변:")
    ]

    response = llm.invoke(messages)
    return response.content


def build_search_query(query: str, user_condition: dict) -> str:
    """
    user_condition을 자연어로 쿼리에 보강
    예) "청년 월세 지원" + {region: "서울", age: 28} → "청년 월세 지원 서울 만 28세"
    """
    if not user_condition:
        return query

    parts = [query]
    if user_condition.get("region"):
        parts.append(user_condition["region"])
    if user_condition.get("age"):
        parts.append(f"만 {user_condition['age']}세")
    if user_condition.get("income_level"):
        parts.append(user_condition["income_level"])
    if user_condition.get("household_type"):
        parts.append(user_condition["household_type"])
    if user_condition.get("employment_status"):
        parts.append(user_condition["employment_status"])

    enriched = " ".join(parts)
    print(f"[쿼리 보강] '{query}' → '{enriched}'")
    return enriched


def benepick_rag(
    user_query: str,
    lang_code: str = "ko",
    user_condition: dict = None,
) -> dict:
    """
    베네픽 RAG 메인 파이프라인
    ① 쿼리 보강 → ② 하이브리드 검색 → ③ Reranking
    → ④ CRAG 품질 검증 → ⑤ LLM 답변 생성

    user_condition: 사용자 조건 정보 (예: {"age": 28, "income_level": "중위소득 52%", "region": "서울"})
    반환값: 팀 공통 성공/실패 응답 형식
    """
    print(f"\n{'='*50}")
    print(f"질문: {user_query}")
    if user_condition:
        print(f"조건: {user_condition}")
    print(f"{'='*50}")

    try:
        # ① 쿼리 보강 (user_condition 반영)
        search_query = build_search_query(user_query, user_condition)

        # ② 하이브리드 검색 (BM25 + 벡터)
        search_start = time.time()
        results = get_searcher().search(search_query, top_k=25, alpha=0.6)
        search_time_ms = round((time.time() - search_start) * 1000)
        if not results:
            return error_response("SEARCH_FAILED", "검색 결과가 없습니다.")
        print(f"[검색] {len(results)}개 후보 검색 완료 ({search_time_ms}ms)")

        # ② Reranking
        reranked = rerank(user_query, results, top_k=5)
        print(f"[Rerank] {len(reranked)}개로 압축")

        # ③ CRAG 품질 검증
        final_docs = crag_quality_check(user_query, reranked)
        print(f"[CRAG] 최종 {len(final_docs)}개 문서 확정")

        # ④ LLM 답변 생성
        answer = generate_answer(user_query, final_docs, lang_code)

        # ── 반환 (팀 공통 응답 형식 + 변수명 규칙) ──
        return success_response({
            "query":          user_query,
            "answer":         answer,
            "lang_code":      lang_code,           # string "ko"/"en" 등
            "user_condition": user_condition,      # dict or None
            "search_time_ms": search_time_ms,      # int, 검색 소요 시간(ms)
            "docs_used":      [
                {
                    "policy_id":   d["policy_id"],    # string "101"
                    "chunk_id":    d["chunk_id"],      # string "101_01"
                    "policy_name": d["policy_name"],
                    "score":       round(float(d["score"]), 4),  # float 0~1
                    "rank":        d["rank"],          # int, 1부터 시작
                }
                for d in final_docs
            ],
            "doc_count":      len(final_docs),      # int
        })

    except Exception as e:
        print(f"[ERROR] {e}")
        return error_response("SEARCH_FAILED", str(e))


# ── 테스트 ──
if __name__ == "__main__":
    import pandas as pd

    test_queries = [
        ("서울 청년 월세 지원 받을 수 있어요?", "ko"),
        ("취업 준비생 훈련비 지원", "ko"),
        ("노인 돌봄 서비스", "ko"),
        ("청년 창업 지원금 받을 수 있나요?", "ko"),
        ("대학생 장학금 신청 방법", "ko"),
        ("장애인 취업 지원 프로그램", "ko"),
        ("장애인 의료비 지원", "ko"),
        ("출산 지원금 얼마나 받을 수 있어요?", "ko"),
        ("어린이집 보육료 지원", "ko"),
        ("기초생활수급자 혜택 뭐가 있어요?", "ko"),
        ("다문화 가정 한국어 교육 지원", "ko"),
        ("disability support benefits", "en"),
    ]

    alpha_values = [0.3, 0.5, 0.6, 0.7, 0.9]  # 0.6은 현재 기준값
    results_data = []

    for alpha in alpha_values:
        print(f"\n{'='*60}")
        print(f"[alpha = {alpha}] 실험")
        print(f"{'='*60}")

        alpha_qualities = []

        for query, lang in test_queries:
            # alpha 값 적용해서 검색
            results = get_searcher().search(query, top_k=25, alpha=alpha)
            reranked = rerank(query, results, top_k=5)
            final_docs = crag_quality_check(query, reranked)

            scores = get_reranker().compute_score(
                [[query, d["evidence_text"]] for d in final_docs],
                normalize=True
            )
            quality = round(sum(scores) / len(scores), 3)
            alpha_qualities.append(quality)

            print(f"질문: {query[:20]}... | 품질: {quality:.3f}")

            results_data.append({
                "alpha":   alpha,
                "질문":    query,
                "품질 점수": quality,
                "사용된 정책": ", ".join([d["policy_name"] for d in final_docs]),
            })

        avg = round(sum(alpha_qualities) / len(alpha_qualities), 3)
        print(f"\n▶ alpha={alpha} 평균 품질: {avg:.3f}")

    df = pd.DataFrame(results_data)
    df.to_excel("실험결과_alpha비교.xlsx", index=False)
    print("\n\n엑셀 저장 완료! -> 실험결과_alpha비교.xlsx")

    # alpha별 평균 요약
    summary = df.groupby("alpha")["품질 점수"].mean().round(3)
    print("\nalpha별 평균 품질 점수")
    print(summary)
