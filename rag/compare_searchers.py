"""
BM25 하이브리드 vs BGE-M3 Sparse 하이브리드 비교 실험 (compare_searchers.py)
─────────────────────────────────────────────────────────────────────────────
비교 대상:
  A. BM25 + BGE-M3 Dense  (현재 searcher.py — HybridSearcher)
  B. BGE-M3 Sparse + Dense (searcher_sparse.py — SparseHybridSearcher)

평가 지표: faithfulness, answer_relevancy (Ragas)
실행: python compare_searchers.py
"""

import json
import numpy as np
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from pipeline import rerank, crag_quality_check, generate_answer
from langchain_ollama import ChatOllama
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_community.embeddings import HuggingFaceEmbeddings
from datasets import Dataset

load_dotenv()

# ── 테스트 질문 (15개 — Ragas 평가 시간 고려) ──────────────────
TEST_QUESTIONS = [
    "서울 청년 월세 지원 받을 수 있나요?",
    "취업 준비생이 받을 수 있는 훈련비 지원이 뭐가 있나요?",
    "청년 창업 지원금 신청 방법 알려주세요",
    "65세 이상 혼자 사는 노인 지원 정책",
    "노인 돌봄 서비스 신청 방법",
    "장애인 취업 지원 프로그램 알려줘",
    "장애인 의료비 지원 혜택",
    "기초생활수급자 혜택 뭐가 있어요?",
    "출산 지원금 얼마나 받을 수 있어요?",
    "어린이집 보육료 지원 신청",
    "한부모 가정 아동 양육비 지원",
    "다문화 가정 한국어 교육 지원",
    "실직한 30대 신청할 수 있는 복지 정책",
    "주거급여 신청 자격",
    "암 환자 의료비 지원 방법",
]


# ── 점수 안전 추출 헬퍼 ───────────────────────────────────────
def safe_score(val) -> float:
    if isinstance(val, list):
        return float(np.nanmean([v for v in val if v is not None]))
    if val is None:
        return 0.0
    return float(val)


# ── RAG 파이프라인 실행 ────────────────────────────────────────
def run_pipeline(question: str, searcher, llm) -> dict | None:
    """검색기 종류에 상관없이 동일 파이프라인 실행"""
    try:
        results = searcher.search(question, top_k=25, alpha=0.6)
        if not results:
            return None

        reranked   = rerank(question, results, top_k=5)
        final_docs = crag_quality_check(question, reranked)
        answer     = generate_answer(question, final_docs, lang_code="ko")

        return {
            "question": question,
            "answer":   answer,
            "contexts": [d["evidence_text"] for d in final_docs],
        }
    except Exception as e:
        print(f"  [ERROR] '{question[:20]}...' → {e}")
        return None


# ── Ragas 평가 ────────────────────────────────────────────────
def run_ragas(dataset_rows: list, ragas_llm, ragas_emb) -> dict:
    dataset = Dataset.from_list(dataset_rows)
    result  = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=ragas_llm,
        embeddings=ragas_emb,
    )
    faith     = safe_score(result["faithfulness"])
    relevancy = safe_score(result["answer_relevancy"])
    avg       = round((faith + relevancy) / 2, 4)
    return {
        "faithfulness":     round(faith, 4),
        "answer_relevancy": round(relevancy, 4),
        "average":          avg,
        "df":               result.to_pandas(),
    }


# ── 메인 ──────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("BM25 하이브리드 vs BGE-M3 Sparse 비교 실험")
    print("=" * 60)

    # 공통 LLM / Ragas 초기화
    llm = ChatOllama(model="gemma3:1b", temperature=0.3)
    ragas_llm = LangchainLLMWrapper(llm)
    # Ragas 임베딩은 경량 모델 사용 (BGE-M3 중복 로딩 방지)
    ragas_emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name="jhgan/ko-sroberta-multitask",
            model_kwargs={"device": "cpu"},
        )
    )

    # ── 실험 A: BM25 하이브리드 ──────────────────────────────
    print("\n[실험 A] BM25 + BGE-M3 Dense 하이브리드")
    print("-" * 40)
    from searcher import HybridSearcher
    import pipeline as _pipeline
    searcher_bm25 = HybridSearcher(device="cpu")
    # pipeline의 _searcher에 주입 → crag_quality_check 내부 get_searcher()가 재로딩 방지
    _pipeline._searcher = searcher_bm25

    rows_bm25 = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"  ({i}/{len(TEST_QUESTIONS)}) {q[:30]}...")
        row = run_pipeline(q, searcher_bm25, llm)
        if row:
            rows_bm25.append(row)

    print(f"\n  수집: {len(rows_bm25)}/{len(TEST_QUESTIONS)}개")
    print("  Ragas 평가 중...")
    result_bm25 = run_ragas(rows_bm25, ragas_llm, ragas_emb)
    print(f"  faithfulness:     {result_bm25['faithfulness']:.4f}")
    print(f"  answer_relevancy: {result_bm25['answer_relevancy']:.4f}")
    print(f"  평균:             {result_bm25['average']:.4f}")

    # BGE-M3 Dense 모델 명시적 해제 (실험 B 로딩 전 CPU RAM 확보)
    import gc, torch
    _pipeline._searcher = None  # pipeline 참조 해제
    del searcher_bm25
    gc.collect()
    torch.cuda.empty_cache()

    # ── 실험 B: BGE-M3 Sparse 하이브리드 ─────────────────────
    print("\n[실험 B] BGE-M3 Sparse + Dense 하이브리드")
    print("-" * 40)
    from searcher_sparse import SparseHybridSearcher
    searcher_sparse = SparseHybridSearcher()
    _pipeline._searcher = searcher_sparse  # crag_quality_check 내부 재검색도 sparse로

    rows_sparse = []
    for i, q in enumerate(TEST_QUESTIONS, 1):
        print(f"  ({i}/{len(TEST_QUESTIONS)}) {q[:30]}...")
        row = run_pipeline(q, searcher_sparse, llm)
        if row:
            rows_sparse.append(row)

    print(f"\n  수집: {len(rows_sparse)}/{len(TEST_QUESTIONS)}개")
    print("  Ragas 평가 중...")
    result_sparse = run_ragas(rows_sparse, ragas_llm, ragas_emb)
    print(f"  faithfulness:     {result_sparse['faithfulness']:.4f}")
    print(f"  answer_relevancy: {result_sparse['answer_relevancy']:.4f}")
    print(f"  평균:             {result_sparse['average']:.4f}")

    # ── 최종 비교 출력 ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("최종 비교 결과")
    print("=" * 60)
    print(f"{'검색기':<30} {'faithfulness':<15} {'relevancy':<12} {'평균'}")
    print("-" * 60)
    print(f"{'BM25 + Dense':<30} {result_bm25['faithfulness']:<15.4f} {result_bm25['answer_relevancy']:<12.4f} {result_bm25['average']:.4f}")
    print(f"{'Sparse + Dense':<30} {result_sparse['faithfulness']:<15.4f} {result_sparse['answer_relevancy']:<12.4f} {result_sparse['average']:.4f}")

    winner = "BM25 하이브리드" if result_bm25["average"] >= result_sparse["average"] else "BGE-M3 Sparse 하이브리드"
    print(f"\n▶ 승자: {winner}")

    # ── 결과 저장 ─────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    summary = {
        "timestamp":      timestamp,
        "num_questions":  len(TEST_QUESTIONS),
        "bm25_hybrid": {
            "faithfulness":     result_bm25["faithfulness"],
            "answer_relevancy": result_bm25["answer_relevancy"],
            "average":          result_bm25["average"],
        },
        "sparse_hybrid": {
            "faithfulness":     result_sparse["faithfulness"],
            "answer_relevancy": result_sparse["answer_relevancy"],
            "average":          result_sparse["average"],
        },
        "winner": winner,
    }

    json_path = f"실험결과_검색기비교_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 저장: {json_path}")

    # 쿼리별 상세 결과 Excel
    df_bm25           = result_bm25["df"].copy()
    df_bm25["검색기"] = "BM25 하이브리드"
    df_bm25["question"] = [r["question"] for r in rows_bm25]

    df_sparse           = result_sparse["df"].copy()
    df_sparse["검색기"] = "Sparse 하이브리드"
    df_sparse["question"] = [r["question"] for r in rows_sparse]

    df_all = pd.concat([df_bm25, df_sparse], ignore_index=True)
    excel_path = f"실험결과_검색기비교_{timestamp}.xlsx"
    df_all.to_excel(excel_path, index=False)
    print(f"Excel 저장: {excel_path}")

    print("\n실험 완료!")
    return summary


if __name__ == "__main__":
    main()
