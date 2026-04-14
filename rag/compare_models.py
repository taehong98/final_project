"""
임베딩 모델 비교 실험 (compare_models.py)
─────────────────────────────────────────
비교 모델:
  1. BAAI/bge-m3               (1024 dim, 현재 베이스라인)
  2. intfloat/multilingual-e5-large  (1024 dim, Microsoft)
  3. Alibaba-NLP/gte-Qwen2-1.5B-instruct (1536 dim)

방식:
  - 문서 1,000건 샘플 → 각 모델로 임베딩
  - 30개 테스트 쿼리로 코사인 유사도 검색 (top-25)
  - bge-reranker-v2-m3로 점수 측정 (품질 프록시)
  - 검색 속도 측정

실행: python compare_models.py
"""

import time
import json
import numpy as np
import pandas as pd
from datetime import datetime
from sentence_transformers import SentenceTransformer
from FlagEmbedding import FlagReranker
from sklearn.metrics.pairwise import cosine_similarity

# ── 설정 ──────────────────────────────────────────────────────
SAMPLE_SIZE = 1000   # 문서 샘플 수 (전체 10,367 중)
TOP_K       = 25     # 검색 후보 수
RERANK_TOP  = 5      # 최종 결과 수
RANDOM_SEED = 42

MODELS = [
    {
        "name":   "bge-m3",
        "model":  "BAAI/bge-m3",
        "dim":    1024,
        "prefix": {"query": "", "doc": ""},          # 자체 처리
    },
    {
        "name":   "multilingual-e5-large",
        "model":  "intfloat/multilingual-e5-large",
        "dim":    1024,
        "prefix": {"query": "query: ", "doc": "passage: "},  # e5 필수 prefix
    },
    {
        "name":        "gte-Qwen2-1.5B",
        "model":       "Alibaba-NLP/gte-Qwen2-1.5B-instruct",
        "dim":         1536,
        "prefix":      {"query": "", "doc": ""},
        "model_kwargs": {"torch_dtype": "float16"},  # fp16으로 절반 메모리 (7.1GB → 3.5GB)
        "device":       "cuda",  # CPU RAM 부족으로 CUDA 사용 (Reranker 2.5GB + Qwen 3.5GB = 6GB)
    },
]

TEST_QUERIES = [
    "서울 청년 월세 지원 받을 수 있나요?",
    "취업 준비생이 받을 수 있는 훈련비 지원이 뭐가 있나요?",
    "청년 창업 지원금 신청 방법 알려주세요",
    "대학생이 받을 수 있는 장학금 종류",
    "청년 주거 지원 정책 알려줘",
    "65세 이상 혼자 사는 노인 지원 정책",
    "노인 돌봄 서비스 신청 방법",
    "기초연금 받으려면 어떻게 해야 하나요?",
    "장애인 취업 지원 프로그램 알려줘",
    "장애인 의료비 지원 혜택",
    "기초생활수급자 혜택 뭐가 있어요?",
    "긴급복지지원 신청 조건",
    "출산 지원금 얼마나 받을 수 있어요?",
    "어린이집 보육료 지원 신청",
    "한부모 가정 아동 양육비 지원",
    "다문화 가정 한국어 교육 지원",
    "실직한 30대 신청할 수 있는 복지 정책",
    "국민취업지원제도 신청 방법",
    "소상공인 자금 지원 받을 수 있는 조건",
    "전세 사기 피해자 지원 정책",
    "주거급여 신청 자격",
    "암 환자 의료비 지원 방법",
    # 다국어
    "Youth housing support in Seoul",                    # 영어
    "青年住房支持政策",                                   # 중국어
    "청년 주거 지원 chính sách",                          # 베트남어 혼용
    "障害者 支援 福祉",                                   # 일본어
]


def load_corpus(sample_size: int) -> pd.DataFrame:
    """복지로 + 정부24 청크 로드 후 샘플링"""
    df1 = pd.read_csv("data/processed/chunks.csv")
    df2 = pd.read_csv("data/processed/gov24/chunks.csv")
    df  = pd.concat([df1, df2], ignore_index=True)
    return df.sample(n=sample_size, random_state=RANDOM_SEED).reset_index(drop=True)


MAX_CHARS = 1000  # 한국어 기준 약 500토큰, OOM 방지용

def embed_texts(model: SentenceTransformer, texts: list, prefix: str = "", batch_size: int = 32) -> np.ndarray:
    """텍스트 리스트 임베딩 (normalize=True)"""
    # 텍스트 길이 제한 (모든 모델 동일 조건, OOM 방지)
    texts = [t[:MAX_CHARS] for t in texts]
    if prefix:
        texts = [prefix + t for t in texts]
    return model.encode(
        texts,
        normalize_embeddings=True,
        batch_size=batch_size,
        show_progress_bar=True,
    )


def retrieve(query_emb: np.ndarray, doc_embs: np.ndarray, df: pd.DataFrame, top_k: int) -> list:
    """코사인 유사도 기반 검색"""
    sims = cosine_similarity(query_emb.reshape(1, -1), doc_embs)[0]
    top_indices = np.argsort(sims)[::-1][:top_k]
    results = []
    for rank, idx in enumerate(top_indices, 1):
        results.append({
            "rank":          rank,
            "score":         float(sims[idx]),
            "policy_name":   df.iloc[idx]["policy_name"],
            "evidence_text": df.iloc[idx]["text"],
        })
    return results


def run_experiment(model_cfg: dict, df: pd.DataFrame, reranker: FlagReranker) -> dict:
    """모델 1개 실험 실행"""
    print(f"\n{'='*60}")
    print(f"모델: {model_cfg['name']} ({model_cfg['dim']}dim)")
    print(f"{'='*60}")

    # 모델 로드 (device는 모델별 설정, 기본 cpu)
    print("모델 로딩 중...")
    load_start = time.time()
    model_kwargs = model_cfg.get("model_kwargs", {})
    device = model_cfg.get("device", "cpu")
    model = SentenceTransformer(model_cfg["model"], device=device, model_kwargs=model_kwargs)
    model.max_seq_length = 512  # 긴 텍스트 OOM 방지 (모든 모델 동일 조건)
    load_time = round(time.time() - load_start, 1)
    print(f"로딩 완료: {load_time}초")

    # 문서 임베딩
    print(f"문서 {len(df)}건 임베딩 중...")
    doc_start = time.time()
    doc_embs = embed_texts(model, df["text"].tolist(), prefix=model_cfg["prefix"]["doc"])
    doc_time = round(time.time() - doc_start, 1)
    print(f"문서 임베딩 완료: {doc_time}초")

    # 쿼리별 실험
    query_results = []
    total_search_ms = 0

    for query in TEST_QUERIES:
        # 쿼리 임베딩
        q_emb = embed_texts(model, [query], prefix=model_cfg["prefix"]["query"])[0]

        # 검색
        search_start = time.time()
        candidates = retrieve(q_emb, doc_embs, df, top_k=TOP_K)
        search_ms  = round((time.time() - search_start) * 1000)
        total_search_ms += search_ms

        # Reranker 점수
        pairs  = [[query, c["evidence_text"]] for c in candidates]
        scores = reranker.compute_score(pairs, normalize=True)
        top5   = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)[:RERANK_TOP]

        avg_score = round(float(np.mean([s for _, s in top5])), 4)
        top1_doc  = top5[0][0]["policy_name"] if top5 else ""

        query_results.append({
            "query":      query,
            "avg_score":  avg_score,
            "search_ms":  search_ms,
            "top1":       top1_doc,
        })
        print(f"  [{avg_score:.4f}] {query[:30]}...")

    # 집계
    avg_quality   = round(float(np.mean([r["avg_score"]  for r in query_results])), 4)
    avg_search_ms = round(float(np.mean([r["search_ms"]  for r in query_results])))

    summary = {
        "model":          model_cfg["name"],
        "dim":            model_cfg["dim"],
        "load_time_sec":  load_time,
        "doc_embed_sec":  doc_time,
        "avg_quality":    avg_quality,
        "avg_search_ms":  avg_search_ms,
        "query_results":  query_results,
    }

    print(f"\n▶ 평균 품질 점수: {avg_quality:.4f}")
    print(f"▶ 평균 검색 시간: {avg_search_ms}ms")

    # 메모리 해제
    del model
    import torch, gc
    torch.cuda.empty_cache()
    gc.collect()

    return summary


def main():
    print("=" * 60)
    print("임베딩 모델 비교 실험")
    print("=" * 60)

    # 공통 데이터 로드
    print(f"\n문서 {SAMPLE_SIZE}건 샘플 로드 중...")
    df = load_corpus(SAMPLE_SIZE)
    print(f"로드 완료: {len(df)}건")

    # Reranker 로드 (공통 품질 평가 도구)
    print("\nbge-reranker-v2-m3 로딩 중...")
    reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True, device="cuda")
    print("Reranker 로딩 완료")

    # 각 모델 실험
    all_results = []
    for model_cfg in MODELS:
        result = run_experiment(model_cfg, df, reranker)
        all_results.append(result)

    # 최종 비교 출력
    print("\n" + "=" * 60)
    print("최종 비교 결과")
    print("=" * 60)
    print(f"{'모델':<30} {'품질':<10} {'검색속도':<12} {'문서임베딩'}")
    print("-" * 60)
    for r in sorted(all_results, key=lambda x: x["avg_quality"], reverse=True):
        print(f"{r['model']:<30} {r['avg_quality']:<10.4f} {r['avg_search_ms']:<12}ms {r['doc_embed_sec']}초")

    # 결과 저장
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")

    # 상세 쿼리별 결과 Excel
    rows = []
    for r in all_results:
        for q in r["query_results"]:
            rows.append({
                "모델":        r["model"],
                "차원":        r["dim"],
                "질문":        q["query"],
                "품질점수":    q["avg_score"],
                "검색시간(ms)": q["search_ms"],
                "1위 정책":    q["top1"],
            })
    df_out = pd.DataFrame(rows)
    excel_path = f"실험결과_모델비교_{timestamp}.xlsx"
    df_out.to_excel(excel_path, index=False)
    print(f"\n상세 결과 저장: {excel_path}")

    # 요약 JSON
    summary = {
        "timestamp":   timestamp,
        "sample_size": SAMPLE_SIZE,
        "models": [
            {
                "model":         r["model"],
                "dim":           r["dim"],
                "avg_quality":   r["avg_quality"],
                "avg_search_ms": r["avg_search_ms"],
                "doc_embed_sec": r["doc_embed_sec"],
                "load_time_sec": r["load_time_sec"],
            }
            for r in all_results
        ],
    }
    json_path = f"실험결과_모델비교_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"요약 결과 저장: {json_path}")

    print("\n실험 완료!")


if __name__ == "__main__":
    main()
