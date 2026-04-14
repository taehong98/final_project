# searcher_sparse.py
import pandas as pd
import numpy as np
import chromadb
from FlagEmbedding import BGEM3FlagModel

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "benepick_policies"
MODEL_NAME = "BAAI/bge-m3"


class SparseHybridSearcher:
    def __init__(self):
        print("BGE-M3 Sparse 하이브리드 검색기 초기화 중...")

        # Chroma DB 연결
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        self.collection = client.get_collection(COLLECTION_NAME)

        # 청크 데이터 로드 (복지로 + 정부24 합치기)
        df_welfare = pd.read_csv("data/processed/chunks.csv")
        df_gov24 = pd.read_csv("data/processed/gov24/chunks.csv")
        self.df_chunks = pd.concat([df_welfare, df_gov24], ignore_index=True)
        print(f"전체 청크 로드: {len(self.df_chunks)}개")

        # BGE-M3 모델 로드 (Dense + Sparse 동시 지원)
        print("BGE-M3 모델 로딩 중...")
        self.model = BGEM3FlagModel(MODEL_NAME, use_fp16=True)

        print("초기화 완료!\n")

    def search(self, query: str, top_k: int = 5, alpha: float = 0.6) -> list:
        """
        BGE-M3 Dense + Sparse 하이브리드 검색
        BM25 없이 BGE-M3 단독으로 하이브리드 검색
        alpha: Dense 비중 (0~1)
        """
        # Dense + Sparse 동시 추출
        embeddings = self.model.encode(
            [query],
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False  # 속도 이슈로 스킵
        )

        dense_vec  = embeddings['dense_vecs'][0]
        sparse_vec = embeddings['lexical_weights'][0]

        # ① Dense 검색 (ChromaDB)
        dense_results = self.collection.query(
            query_embeddings=[dense_vec.tolist()],
            n_results=top_k * 5  # 넉넉하게 가져오기
        )

        # chunk_id → Dense 점수
        dense_scores = {}
        for i, chunk_id in enumerate(dense_results["ids"][0]):
            score = 1 - dense_results["distances"][0][i]
            dense_scores[chunk_id] = score

        # ② Sparse 점수 계산
        sparse_scores = {}
        chunk_ids = self.df_chunks["chunk_id"].tolist()
        texts = self.df_chunks["text"].tolist()

        for chunk_id, text in zip(chunk_ids, texts):
            sparse_score = sum(
                sparse_vec.get(token, 0)
                for token in text.split()
            )
            sparse_scores[chunk_id] = float(sparse_score)

        # Sparse 점수 정규화 (0~1)
        max_sparse = max(sparse_scores.values()) + 1e-9
        sparse_scores = {k: v / max_sparse for k, v in sparse_scores.items()}

        # ③ 최종 점수 합산
        all_ids = set(dense_scores.keys()) | set(sparse_scores.keys())
        final_scores = {}
        for chunk_id in all_ids:
            d = dense_scores.get(chunk_id, 0)
            s = sparse_scores.get(chunk_id, 0)
            final_scores[chunk_id] = alpha * d + (1 - alpha) * s

        # ④ Top-K 추출
        top_ids = sorted(
            final_scores,
            key=final_scores.get,
            reverse=True
        )[:top_k]

        # ⑤ 결과 조합
        results = []
        for rank, chunk_id in enumerate(top_ids, 1):
            rows = self.df_chunks[self.df_chunks["chunk_id"] == chunk_id]
            if rows.empty:
                continue
            row = rows.iloc[0]
            results.append({
                "rank":         rank,
                "chunk_id":     chunk_id,
                "policy_id":    row["policy_id"],
                "policy_name":  row["policy_name"],
                "category":     row["category"],
                "region":       row["region"],
                "source_url":   row["source_url"],
                "score":        round(final_scores[chunk_id], 4),
                "dense_score":  round(dense_scores.get(chunk_id, 0), 4),
                "sparse_score": round(sparse_scores.get(chunk_id, 0), 4),
                "evidence_text": row["text"],
            })

        return results


def print_results(results, query):
    print(f"\n{'='*50}")
    print(f"검색어: '{query}'")
    print(f"{'='*50}")
    for r in results:
        print(f"\n[{r['rank']}위] {r['policy_name']} ({r['category']})")
        print(f"  최종 점수: {r['score']} (Dense: {r['dense_score']} / Sparse: {r['sparse_score']})")
        print(f"  내용: {r['evidence_text'][:80]}...")


if __name__ == "__main__":
    searcher = SparseHybridSearcher()

    queries = [
        "서울 청년 월세 지원",
        "취업 준비생 훈련비 지원",
        "외국인 다문화 가정 복지",
        "노인 돌봄 서비스",
    ]

    for query in queries:
        results = searcher.search(query, top_k=3, alpha=0.6)
        print_results(results, query)

    print("\n\nBGE-M3 Sparse 하이브리드 검색 완료!")