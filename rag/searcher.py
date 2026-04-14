import pandas as pd
import numpy as np
import chromadb
import os
from pathlib import Path
from rank_bm25 import BM25Okapi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_PATH = PROJECT_ROOT / "processed"
CACHE_ROOT = PROJECT_ROOT / ".cache" / "huggingface"
os.environ.setdefault("HF_HOME", str(CACHE_ROOT))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(CACHE_ROOT / "sentence-transformers"))

from sentence_transformers import SentenceTransformer

CHROMA_PATH = str(PROJECT_ROOT)
COLLECTION_NAME = "benepick_policies"
MODEL_NAME = "BAAI/bge-m3"

# 한국어 조사/어미 목록 (길이 내림차순 정렬로 최장 매칭)
_JOSA = sorted([
    '으로부터', '에게서', '에서부터', '로부터',
    '에서', '에게', '한테', '으로', '에서',
    '에서', '까지', '부터', '처럼', '만큼', '보다',
    '에', '의', '을', '를', '이', '가', '은', '는',
    '과', '와', '도', '만', '로', '야', '아',
], key=len, reverse=True)


def tokenize(text: str) -> list[str]:
    """
    한국어 경량 토크나이저
    - 공백 분리 후 조사/어미 제거
    - 원형 + 조사 제거형 둘 다 인덱싱 (재현율 향상)
    - 2글자 미만 토큰 제거 (노이즈)
    """
    tokens = []
    for word in text.split():
        if len(word) < 2:
            continue
        tokens.append(word)  # 원형 추가

        # 조사 제거 후 어근 추가
        for josa in _JOSA:
            if word.endswith(josa) and len(word) - len(josa) >= 2:
                stem = word[:-len(josa)]
                tokens.append(stem)
                break

    return tokens


class HybridSearcher:
    def __init__(self, device="cuda"):
        print("하이브리드 검색기 초기화 중...")

        # Chroma DB 연결
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        self.collection = client.get_collection(COLLECTION_NAME)

        # 정책 데이터 로드 (복지로 + 정부24)
        df_welfare = pd.read_csv(PROCESSED_PATH / "chunks.csv")
        df_gov24   = pd.read_csv(PROCESSED_PATH / "gov24" / "chunks.csv")
        self.df_chunks = pd.concat([df_welfare, df_gov24], ignore_index=True)

        # chunk_id 인덱싱 → O(1) 조회
        self.df_chunks = self.df_chunks.set_index("chunk_id", drop=False)
        print(f"전체 정책 로드: {len(self.df_chunks)}개")

        # BGE-M3 모델 로드
        print("BGE-M3 모델 로딩 중...")
        self.model = SentenceTransformer(MODEL_NAME, device=device)

        # BM25 초기화 (Kiwi 형태소 분석)
        print("BM25 인덱스 생성 중 (Kiwi 형태소 분석)...")
        tokenized = [tokenize(text) for text in self.df_chunks["text"].tolist()]
        self.bm25 = BM25Okapi(tokenized)
        self.chunk_ids = self.df_chunks["chunk_id"].tolist()

        print("초기화 완료!\n")

    def vector_search(self, query: str, top_k: int = 10) -> dict:
        """벡터 유사도 검색"""
        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True
        ).tolist()

        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=top_k
        )

        # chunk_id → 점수 딕셔너리 (거리 → 유사도)
        return {
            chunk_id: 1 - dist
            for chunk_id, dist in zip(results["ids"][0], results["distances"][0])
        }

    def bm25_search(self, query: str) -> dict:
        """BM25 키워드 검색 (Kiwi 형태소 분석)"""
        tokenized_query = tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)

        # 정규화 (0~1)
        max_score = max(scores) + 1e-9
        normalized = scores / max_score

        return {
            chunk_id: float(normalized[i])
            for i, chunk_id in enumerate(self.chunk_ids)
        }

    def search(self, query: str, top_k: int = 5, alpha: float = 0.6) -> list:
        """
        하이브리드 검색
        alpha=0.6 → 벡터 60% + BM25 40%
        """
        # 1. 벡터 검색 + BM25 검색
        vector_scores = self.vector_search(query, top_k=top_k * 2)
        bm25_scores   = self.bm25_search(query)

        # 2. 점수 합산
        all_ids = set(vector_scores.keys()) | set(bm25_scores.keys())
        final_scores = {
            cid: alpha * vector_scores.get(cid, 0) + (1 - alpha) * bm25_scores.get(cid, 0)
            for cid in all_ids
        }

        # 3. Top-K 추출
        top_ids = sorted(final_scores, key=final_scores.get, reverse=True)[:top_k]

        # 4. 결과 조합 (set_index로 O(1) 조회)
        results = []
        for rank, chunk_id in enumerate(top_ids, 1):
            row = self.df_chunks.loc[chunk_id]
            results.append({
                "rank":          rank,
                "chunk_id":      chunk_id,
                "policy_id":     row["policy_id"],
                "policy_name":   row["policy_name"],
                "category":      row["category"],
                "region":        row["region"],
                "source_url":    row["source_url"],
                "score":         round(final_scores[chunk_id], 4),
                "vector_score":  round(vector_scores.get(chunk_id, 0), 4),
                "bm25_score":    round(bm25_scores.get(chunk_id, 0), 4),
                "evidence_text": row["text"],
            })

        return results


def print_results(results, query):
    print(f"\n{'='*50}")
    print(f"검색어: '{query}'")
    print(f"{'='*50}")
    for r in results:
        print(f"\n[{r['rank']}위] {r['policy_name']} ({r['category']})")
        print(f"  최종 점수: {r['score']} (벡터: {r['vector_score']} / BM25: {r['bm25_score']})")
        print(f"  지역: {r['region']}")
        print(f"  내용: {r['evidence_text'][:80]}...")


if __name__ == "__main__":
    searcher = HybridSearcher()

    queries = [
        "서울 청년 월세 지원",
        "취업 준비생 훈련비 지원",
        "기초연금 받으려면",
        "실직한 30대 복지 정책",
        "노인 돌봄 서비스",
    ]

    for query in queries:
        results = searcher.search(query, top_k=3, alpha=0.6)
        print_results(results, query)

    print("\n하이브리드 검색 완료!")
