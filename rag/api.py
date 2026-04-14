from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from .pipeline import (
        benepick_rag,
        get_searcher,
        rerank,
        crag_quality_check,
        generate_answer,
        success_response,
        error_response,
        build_search_query,
    )
except ImportError:
    from pipeline import (
        benepick_rag,
        get_searcher,
        rerank,
        crag_quality_check,
        generate_answer,
        success_response,
        error_response,
        build_search_query,
    )
import time
from datetime import datetime
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    # 서버 시작 시 BGE-M3 미리 로딩 (첫 요청 지연 방지)
    print("[워밍업] BGE-M3 searcher 로딩 중...")
    get_searcher()
    print("[워밍업] 완료")
    yield

app = FastAPI(title="BenePick RAG API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UserCondition(BaseModel):
    age: int | None = None
    region: str | None = None
    income_level: str | None = None
    household_type: str | None = None
    employment_status: str | None = None
    housing_type: str | None = None


class SearchRequest(BaseModel):
    query: str
    user_condition: UserCondition | None = None
    lang_code: str = "ko"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/rag/search")
def rag_search(req: SearchRequest) -> dict:
    condition = req.user_condition.model_dump(exclude_none=True) if req.user_condition else None
    return benepick_rag(
        user_query=req.query,
        lang_code=req.lang_code,
        user_condition=condition,
    )


@app.post("/rag/search/v2")
def rag_search_v2(req: SearchRequest) -> dict:
    """
    [실험용] 검색 결과 목록 + LLM 답변 분리 반환
    - search_results: reranker 점수 순 전체 결과 (top 25)
    - answer: top 5 기준 LLM 답변
    """
    try:
        condition = req.user_condition.model_dump(exclude_none=True) if req.user_condition else None

        # ① 쿼리 보강 + 하이브리드 검색 (top 25)
        search_query = build_search_query(req.query, condition)
        search_start = time.time()
        results = get_searcher().search(search_query, top_k=25, alpha=0.6)
        search_time_ms = round((time.time() - search_start) * 1000)
        if not results:
            return error_response("SEARCH_FAILED", "검색 결과가 없습니다.")

        # ② 전체 25개 rerank (점수 계산)
        all_reranked = rerank(req.query, results, top_k=25)

        # ③ top 5로 CRAG + LLM 답변 생성
        top5 = all_reranked[:5]
        final_docs = crag_quality_check(req.query, top5)
        answer = generate_answer(req.query, final_docs, lang_code=req.lang_code)

        return success_response({
            "query":          req.query,
            "answer":         answer,
            "lang_code":      req.lang_code,
            "user_condition": condition,
            "search_time_ms": search_time_ms,
            # 검색 결과 전체 (관련도 순) — 태홍님이 인기도와 합산해서 최종 정렬
            "search_results": [
                {
                    "policy_id":   d["policy_id"],
                    "chunk_id":    d["chunk_id"],
                    "policy_name": d["policy_name"],
                    "score":       round(float(d["score"]), 4),
                    "rank":        i + 1,
                    "category":    d.get("category", ""),
                    "region":      d.get("region", ""),
                    "source_url":  d.get("source_url", ""),
                    "evidence_text": d.get("evidence_text", ""),
                }
                for i, d in enumerate(all_reranked)
            ],
            "total_count": len(all_reranked),
            # LLM이 참고한 문서 수
            "docs_used_count": len(final_docs),
        })

    except Exception as e:
        print(f"[ERROR] {e}")
        return error_response("SEARCH_FAILED", str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
