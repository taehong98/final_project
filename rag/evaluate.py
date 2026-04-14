"""
베네픽 RAG 평가 스크립트 (evaluate.py)
─────────────────────────────────────
평가 지표: faithfulness, answer_relevancy
ground_truth 없이 돌아가는 2개로 구성
사용법: python evaluate.py
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# 파이프라인 임포트
from searcher import HybridSearcher
from pipeline import rerank, crag_quality_check, generate_answer
from langchain_ollama import ChatOllama

# Ragas
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_community.embeddings import HuggingFaceEmbeddings
from datasets import Dataset

load_dotenv()

# ── 평가용 질문 30개 ──────────────────────────────────────────
TEST_QUESTIONS = [
    # 청년
    "서울 청년 월세 지원 받을 수 있나요?",
    "취업 준비생이 받을 수 있는 훈련비 지원이 뭐가 있나요?",
    "청년 창업 지원금 신청 방법 알려주세요",
    "대학생이 받을 수 있는 장학금 종류",
    "청년 주거 지원 정책 알려줘",
    "만 34세 미만 청년 고용 지원 프로그램",
    "청년 내일채움공제 조건",

    # 노인
    "65세 이상 혼자 사는 노인 지원 정책",
    "노인 돌봄 서비스 신청 방법",
    "기초연금 받으려면 어떻게 해야 하나요?",
    "노인 의료비 지원 제도",

    # 장애인
    "장애인 취업 지원 프로그램 알려줘",
    "장애인 의료비 지원 혜택",
    "장애인 활동 지원 서비스 신청 방법",

    # 저소득·기초생활
    "기초생활수급자 혜택 뭐가 있어요?",
    "긴급복지지원 신청 조건",
    "차상위계층이 받을 수 있는 지원",
    "생계급여 받으려면 소득 기준이 어떻게 되나요?",

    # 출산·육아
    "출산 지원금 얼마나 받을 수 있어요?",
    "어린이집 보육료 지원 신청",
    "한부모 가정 아동 양육비 지원",
    "육아휴직 급여 얼마나 받나요?",

    # 다문화·외국인
    "다문화 가정 한국어 교육 지원",
    "결혼이민자 복지 서비스",

    # 고용·실업
    "실직한 30대 신청할 수 있는 복지 정책",
    "국민취업지원제도 신청 방법",
    "소상공인 자금 지원 받을 수 있는 조건",

    # 주거
    "전세 사기 피해자 지원 정책",
    "주거급여 신청 자격",

    # 의료
    "암 환자 의료비 지원 방법",
]


# ── RAG 파이프라인 실행 ────────────────────────────────────────
def run_rag_pipeline(question: str, searcher: HybridSearcher, llm) -> dict:
    """기존 파이프라인 그대로 돌리고 Ragas 형식으로 반환"""
    try:
        # ① 하이브리드 검색
        results = searcher.search(question, top_k=25, alpha=0.6)
        if not results:
            return None

        # ② Reranking
        reranked = rerank(question, results, top_k=5)

        # ③ CRAG 품질 검증
        final_docs = crag_quality_check(question, reranked)

        # ④ LLM 답변 생성
        answer = generate_answer(question, final_docs, lang_code="ko")

        # ⑤ Ragas 형식 반환
        contexts = [d["evidence_text"] for d in final_docs]

        return {
            "question": question,
            "answer":   answer,
            "contexts": contexts,
        }

    except Exception as e:
        print(f"[ERROR] '{question}' 처리 중 오류: {e}")
        return None


# ── 점수 안전 추출 헬퍼 ───────────────────────────────────────
def safe_score(val) -> float:
    """list/nan/float 어떤 형태든 float로 변환"""
    if isinstance(val, list):
        return float(np.nanmean([v for v in val if v is not None]))
    if val is None:
        return 0.0
    return float(val)


# ── 메인 평가 함수 ────────────────────────────────────────────
def run_evaluation():
    print("=" * 60)
    print("베네픽 RAG 평가 시작")
    print("=" * 60)

    # 초기화
    print("\n[1/4] 파이프라인 초기화 중...")
    searcher = HybridSearcher(device="cpu")
    llm = ChatOllama(model="gemma3:1b", temperature=0.3)

    ragas_llm = LangchainLLMWrapper(llm)
    ragas_emb = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name="BAAI/bge-m3",
            model_kwargs={"device": "cpu"},
        )
    )

    # 데이터 수집
    print(f"\n[2/4] {len(TEST_QUESTIONS)}개 질문 RAG 파이프라인 실행 중...")
    dataset_rows = []

    for i, question in enumerate(TEST_QUESTIONS, 1):
        print(f"  ({i}/{len(TEST_QUESTIONS)}) {question[:30]}...")
        result = run_rag_pipeline(question, searcher, llm)
        if result:
            dataset_rows.append(result)

    print(f"\n  ✅ {len(dataset_rows)}개 수집 완료 ({len(TEST_QUESTIONS) - len(dataset_rows)}개 실패)")

    if not dataset_rows:
        print("평가 가능한 데이터가 없습니다!")
        return

    # Ragas Dataset 변환
    print("\n[3/4] Ragas 평가 실행 중...")
    dataset = Dataset.from_list(dataset_rows)

    result = evaluate(
        dataset=dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
        ],
        llm=ragas_llm,
        embeddings=ragas_emb,
    )

    # 점수 추출 (list/float 둘 다 대응)
    faith_score     = safe_score(result['faithfulness'])
    relevancy_score = safe_score(result['answer_relevancy'])
    avg_score       = round((faith_score + relevancy_score) / 2, 4)

    # 결과 출력
    print("\n" + "=" * 60)
    print("📊 평가 결과")
    print("=" * 60)
    print(f"  faithfulness      (환각 방지):   {faith_score:.4f}")
    print(f"  answer_relevancy  (답변 관련성): {relevancy_score:.4f}")
    print(f"  평균:                            {avg_score:.4f}")

    # 결과 저장
    print("\n[4/4] 결과 저장 중...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    # 상세 결과 DataFrame
    df_result = result.to_pandas()
    df_result["question"] = [r["question"] for r in dataset_rows]
    df_result["answer"]   = [r["answer"]   for r in dataset_rows]

    excel_path = f"실험결과_Ragas_{timestamp}.xlsx"
    df_result.to_excel(excel_path, index=False)
    print(f"  ✅ 상세 결과: {excel_path}")

    # 요약 JSON
    summary = {
        "timestamp":        timestamp,
        "total_questions":  len(dataset_rows),
        "faithfulness":     round(faith_score, 4),
        "answer_relevancy": round(relevancy_score, 4),
        "average":          avg_score,
    }

    json_path = f"실험결과_Ragas_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 요약 결과: {json_path}")

    print("\n평가 완료! 🎉")
    print(f"  평균 점수: {avg_score:.4f}")

    return summary


if __name__ == "__main__":
    run_evaluation()
