import pandas as pd
import numpy as np
import os
import chromadb

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "benepick_policies"


def load_processed_data(path="data/processed/"):
    df_chunks = pd.read_csv(f"{path}chunks.csv")
    embeddings = np.load(f"{path}embeddings.npy")
    print(f"정책 데이터 로드: {len(df_chunks)}개")
    print(f"임베딩 로드: {embeddings.shape}")
    return df_chunks, embeddings


def save_to_chroma(df_chunks, embeddings):
    print(f"\nChroma DB 초기화 중...")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    try:
        client.delete_collection(COLLECTION_NAME)
        print("기존 컬렉션 삭제")
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    metadatas = []
    for _, row in df_chunks.iterrows():
        metadatas.append({
            "policy_id":   row["policy_id"],
            "policy_name": row["policy_name"],
            "category":    row["category"],
            "region":      row["region"],
            "source_url":  row["source_url"],
        })

    collection.add(
        ids=df_chunks["chunk_id"].tolist(),
        embeddings=embeddings.tolist(),
        documents=df_chunks["text"].tolist(),
        metadatas=metadatas
    )

    print(f"Chroma DB 저장 완료! {collection.count()}개 청크")
    return client, collection


def test_search(collection, query="서울 청년 월세 지원", top_k=3):
    from sentence_transformers import SentenceTransformer

    print(f"\n검색 테스트: '{query}'")
    model = SentenceTransformer("BAAI/bge-m3")
    query_embedding = model.encode(
        [query],
        normalize_embeddings=True
    ).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=top_k
    )

    print(f"\n검색 결과 Top-{top_k}:")
    for i in range(len(results["ids"][0])):
        policy_name = results["metadatas"][0][i]["policy_name"]
        category = results["metadatas"][0][i]["category"]
        distance = results["distances"][0][i]
        doc_preview = results["documents"][0][i][:80]
        print(f"\n[{i+1}위]")
        print(f"  정책명: {policy_name}")
        print(f"  카테고리: {category}")
        print(f"  유사도 거리: {distance:.4f}")
        print(f"  내용: {doc_preview}...")


if __name__ == "__main__":
    # 복지로 저장
    df_chunks, embeddings = load_processed_data()
    client, collection = save_to_chroma(df_chunks, embeddings)

    # 정부24 저장 (나눠서 추가)
    df_gov24, embeddings_gov24 = load_processed_data(path="data/processed/gov24/")

    metadatas_gov24 = []
    for _, row in df_gov24.iterrows():
        metadatas_gov24.append({
            "policy_id":   row["policy_id"],
            "policy_name": row["policy_name"],
            "category":    row["category"],
            "region":      row["region"],
            "source_url":  row["source_url"],
        })

    # 5000건씩 나눠서 추가
    batch_size = 5000
    total = len(df_gov24)
    for i in range(0, total, batch_size):
        end = min(i + batch_size, total)
        collection.add(
            ids=df_gov24["chunk_id"].tolist()[i:end],
            embeddings=embeddings_gov24.tolist()[i:end],
            documents=df_gov24["text"].tolist()[i:end],
            metadatas=metadatas_gov24[i:end]
        )
        print(f"  {end}/{total}건 추가 완료")

    # for 루프 밖에 있어야 함 ↓
    print(f"\n정부24 추가 완료! 전체 {collection.count()}개 청크")

    test_search(collection, query="청년 월세 지원")
    test_search(collection, query="취업 준비생 지원금")
    test_search(collection, query="외국인 다문화 가정 복지")

    print("\n벡터 DB 구축 완료!")
    print("다음 단계: 하이브리드 검색 (searcher.py)")