import pandas as pd
import numpy as np
import os
from sentence_transformers import SentenceTransformer
from preprocessor import (
    load_data, process_policies,
    load_gov24_data, process_gov24_policies,
)

MODEL_NAME = "BAAI/bge-m3"


def create_embeddings(model, records: list) -> np.ndarray:
    texts = [r["text"] for r in records]
    print(f"임베딩 생성 중... ({len(texts)}개)")
    embeddings = model.encode(
        texts,
        batch_size=8,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    print(f"임베딩 완료! shape: {embeddings.shape}")
    return embeddings


def save_embeddings(records: list, embeddings: np.ndarray, path: str = "data/processed/"):
    os.makedirs(path, exist_ok=True)

    df = pd.DataFrame([{
        "chunk_id":    r["chunk_id"],
        "policy_id":   r["policy_id"],
        "policy_name": r["policy_name"],
        "category":    r["category"],
        "region":      r["region"],
        "source_url":  r["source_url"],
        "text":        r["text"],
    } for r in records])

    df.to_csv(f"{path}chunks.csv", index=False, encoding="utf-8-sig")
    np.save(f"{path}embeddings.npy", embeddings)

    print(f"저장 완료!")
    print(f"  메타: {path}chunks.csv  ({len(df)}건)")
    print(f"  벡터: {path}embeddings.npy  {embeddings.shape}")


if __name__ == "__main__":
    print("BGE-M3 모델 로딩 중... (처음 실행 시 다운로드 ~2GB)")
    model = SentenceTransformer(MODEL_NAME)

    # 복지로
    print("\n=== 복지로 임베딩 ===")
    df = load_data()
    records = process_policies(df)
    embeddings = create_embeddings(model, records)
    save_embeddings(records, embeddings, path="data/processed/")

    # 정부24
    print("\n=== 정부24 임베딩 ===")
    df_gov24 = load_gov24_data()
    records_gov24 = process_gov24_policies(df_gov24)
    embeddings_gov24 = create_embeddings(model, records_gov24)
    save_embeddings(records_gov24, embeddings_gov24, path="data/processed/gov24/")

    print("\n전체 임베딩 파이프라인 완료!")
