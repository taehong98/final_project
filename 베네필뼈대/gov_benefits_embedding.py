"""
03 임베딩 생성 파이프라인
=========================
BGE-M3 모델로 정책 텍스트를 벡터로 변환하고 FAISS 인덱스를 구축합니다.

수정 사항:
  - [BUG FIX] 증분 모드에서 FAISS 인덱스에 벡터만 추가하고 메타데이터는 전체
    재저장하던 버그 수정 → index position N 과 metadata[N] 불일치 문제 해결
    FAISS IndexFlatIP는 삭제/교체 불가이므로, 변경이 감지되면 항상 전체 재빌드
  - [BUG FIX] build_text()에서 한글 컬럼명 소문자 변환 후 DB 컬럼명과 불일치하던
    문제 수정 → 원본 한글 키와 소문자+언더스코어 변환 키를 모두 시도

사용법:
  python gov_benefits_embedding.py --once        # 전체 임베딩 1회 실행
  python gov_benefits_embedding.py --incremental # 변경분만 감지 후 전체 재빌드 (기본)
  python gov_benefits_embedding.py --reset       # 기존 인덱스 초기화 후 전체 재처리
"""

import os
import json
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import faiss
from sqlalchemy import create_engine, text
from sentence_transformers import SentenceTransformer

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DB_URL     = "sqlite:///gov_benefits.db"
TABLE_NAME = "gov_benefits"
MODEL_NAME = "BAAI/bge-m3"
BATCH_SIZE = 32
INDEX_DIR  = Path("faiss_index")

# 임베딩에 사용할 컬럼 (한글 원본명 기준)
TEXT_COLUMNS = ["서비스명", "서비스목적요약", "지원내용", "지원대상", "선정기준"]

# 메타데이터로 보존할 컬럼
META_COLUMNS = [
    "서비스명", "서비스분야", "지원유형", "소관기관명",
    "신청방법", "신청기한", "접수기관", "전화문의", "상세조회url",
    "지원대상", "선정기준",   # scoring.py에서 조건 파싱에 필요
]

HASH_FILE  = INDEX_DIR / "text_hashes.json"
INDEX_PATH = INDEX_DIR / "gov_benefits.index"
META_PATH  = INDEX_DIR / "metadata.json"

# ──────────────────────────────────────────────
# 로깅
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 1. DB에서 데이터 로드
# ──────────────────────────────────────────────
def load_from_db() -> pd.DataFrame:
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        df = pd.read_sql(f"SELECT * FROM {TABLE_NAME}", conn)
    log.info("DB 로드 완료: %d 행", len(df))
    return df


# ──────────────────────────────────────────────
# 2. 텍스트 결합 — BUG FIX
# ──────────────────────────────────────────────
def _get_col(row: pd.Series, col_name: str) -> str:
    """
    [수정] 한글 컬럼명 + 소문자_언더스코어 변환명 둘 다 시도
    pipeline.py에서 컬럼명을 소문자+언더스코어로 변환하므로
    '서비스목적요약' → '서비스목적요약' (한글은 lower() 영향 없음, 공백만 처리)
    '지원 대상' → '지원_대상' 처럼 공백이 있는 경우를 위해 양쪽 시도
    """
    # 1순위: 원본 한글 그대로
    val = row.get(col_name)
    if val is not None and pd.notna(val):
        return str(val).strip()

    # 2순위: 소문자 + 공백→언더스코어 변환
    db_col = col_name.strip().lower().replace(" ", "_")
    val = row.get(db_col)
    if val is not None and pd.notna(val):
        return str(val).strip()

    return ""


def build_text(row: pd.Series) -> str:
    labels = {
        "서비스명":      "서비스",
        "서비스목적요약": "목적",
        "지원내용":      "지원내용",
        "지원대상":      "대상",
        "선정기준":      "선정기준",
    }
    parts = []
    for col, label in labels.items():
        val = _get_col(row, col)
        if val:
            cleaned = " ".join(val.split())
            parts.append(f"[{label}] {cleaned}")
    return " ".join(parts)


def compute_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ──────────────────────────────────────────────
# 3. 증분 처리 필터
# ──────────────────────────────────────────────
def load_hashes() -> dict:
    if HASH_FILE.exists():
        return json.loads(HASH_FILE.read_text(encoding="utf-8"))
    return {}


def save_hashes(hashes: dict) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")


def has_changes(df: pd.DataFrame, texts: list[str]) -> bool:
    """
    [수정] 변경 여부만 반환 (bool)
    FAISS IndexFlatIP는 벡터 삭제/교체 불가 → 변경이 1건이라도 있으면 전체 재빌드
    """
    saved = load_hashes()
    for i, (_, row) in enumerate(df.iterrows()):
        key = _get_col(row, "서비스명") or str(i)
        if saved.get(key) != compute_hash(texts[i]):
            return True
    return False


# ──────────────────────────────────────────────
# 4. BGE-M3 임베딩
# ──────────────────────────────────────────────
def encode_texts(texts: list[str]) -> np.ndarray:
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("모델 로드: %s (device=%s)", MODEL_NAME, device)
    if device == "cuda":
        log.info("GPU: %s | VRAM: %.1f GB", torch.cuda.get_device_name(0),
                 torch.cuda.get_device_properties(0).total_memory / 1e9)
    model = SentenceTransformer(MODEL_NAME, device=device)

    log.info("임베딩 시작: %d 건 (batch_size=%d)", len(texts), BATCH_SIZE)
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    log.info("임베딩 완료: shape=%s", embeddings.shape)
    return embeddings.astype(np.float32)


# ──────────────────────────────────────────────
# 5. FAISS 인덱스 구축
# ──────────────────────────────────────────────
def build_faiss_index(embeddings: np.ndarray) -> faiss.Index:
    dim   = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    log.info("FAISS 인덱스 구축: %d 벡터, dim=%d", index.ntotal, dim)
    return index


def save_index(index: faiss.Index) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    log.info("FAISS 인덱스 저장: %s (%d 벡터)", INDEX_PATH, index.ntotal)


# ──────────────────────────────────────────────
# 6. 메타데이터 저장 — scoring.py 필드 포함
# ──────────────────────────────────────────────
def save_metadata(df: pd.DataFrame) -> None:
    """
    FAISS index 위치 N → 실제 정책 정보 매핑
    저장 순서가 곧 FAISS index position이므로 df 행 순서와 반드시 1:1 일치해야 함
    """
    records = []
    for _, row in df.iterrows():
        record = {"faiss_idx": len(records)}
        for col in META_COLUMNS:
            val = _get_col(row, col)
            record[col] = val if val else None
        records.append(record)

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info("메타데이터 저장: %d 건 → %s", len(records), META_PATH)


# ──────────────────────────────────────────────
# 7. 검색 테스트 유틸 (개발용)
# ──────────────────────────────────────────────
def search(query: str, top_k: int = 5) -> list[dict]:
    model = SentenceTransformer(MODEL_NAME)
    q_vec = model.encode([query], normalize_embeddings=True, convert_to_numpy=True).astype(np.float32)

    index = faiss.read_index(str(INDEX_PATH))
    meta  = json.loads(META_PATH.read_text(encoding="utf-8"))

    scores, indices = index.search(q_vec, top_k)
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        item = meta[idx].copy()
        item["score"] = round(float(score), 4)
        results.append(item)
    return results


# ──────────────────────────────────────────────
# 8. 메인 파이프라인 — BUG FIX
# ──────────────────────────────────────────────
def run_embedding(incremental: bool = True, reset: bool = False) -> None:
    log.info("=" * 55)
    log.info("  임베딩 파이프라인 시작: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("  모드: %s", "초기화 후 전체" if reset else ("증분 감지 후 전체 재빌드" if incremental else "전체"))
    log.info("=" * 55)

    # 초기화
    if reset:
        for p in [INDEX_PATH, META_PATH, HASH_FILE]:
            if p and Path(str(p)).exists():
                Path(str(p)).unlink()
                log.info("삭제: %s", p)

    # 1) DB 로드
    df = load_from_db()

    # 2) 텍스트 결합
    texts = [build_text(row) for _, row in df.iterrows()]
    log.info("텍스트 결합 완료: %d 건", len(texts))

    # 3) [수정] 증분 모드: 변경 여부 확인만 하고, 변경이 있으면 전체 재빌드
    #    기존 코드는 변경된 행만 인덱스에 추가했으나
    #    FAISS IndexFlatIP는 벡터 삭제/교체 불가 → position↔metadata 불일치 발생
    if incremental and not reset:
        if not has_changes(df, texts):
            log.info("변경된 데이터 없음 — 파이프라인 종료")
            return
        log.info("변경 감지 — 전체 인덱스 재빌드")

    # 4) 임베딩 (전체)
    embeddings = encode_texts(texts)

    # 5) FAISS 인덱스 전체 재빌드
    index = build_faiss_index(embeddings)
    save_index(index)

    # 6) 메타데이터 저장 (df 행 순서 = FAISS index position)
    save_metadata(df)

    # 7) 해시 전체 갱신
    hashes = {}
    for i, (_, row) in enumerate(df.iterrows()):
        key = _get_col(row, "서비스명") or str(i)
        hashes[key] = compute_hash(texts[i])
    save_hashes(hashes)

    log.info("임베딩 파이프라인 완료\n")


# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once",        action="store_true", help="전체 임베딩 1회 실행")
    parser.add_argument("--incremental", action="store_true", help="변경분 감지 후 전체 재빌드 (기본)")
    parser.add_argument("--reset",       action="store_true", help="인덱스 초기화 후 전체 재처리")
    parser.add_argument("--search",      type=str,            help="검색 테스트 쿼리")
    parser.add_argument("--topk",        type=int, default=5, help="검색 결과 수 (기본 5)")
    args = parser.parse_args()

    if args.search:
        results = search(args.search, top_k=args.topk)
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.reset:
        run_embedding(incremental=False, reset=True)
    elif args.once:
        run_embedding(incremental=False)
    else:
        run_embedding(incremental=True)
