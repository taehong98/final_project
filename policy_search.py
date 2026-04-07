from __future__ import annotations

import logging
import re as _re
from pathlib import Path

import chromadb
import pandas as pd
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from sqlalchemy import create_engine, text

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
MODEL_NAME = "BAAI/bge-m3"
CHROMA_PATH = Path("chroma_db")
COLLECTION_NAME = "benepick_policies"
DATA_DIR = Path("data/processed")
WELFARE_CHUNKS_PATH = DATA_DIR / "chunks.csv"
GOV24_CHUNKS_PATH = DATA_DIR / "gov24" / "chunks.csv"

DB_URL = "sqlite:///gov_benefits.db"
TABLE_NAME = "gov_benefits"

TOP_K_DEFAULT = 10
ALPHA_DEFAULT = 0.6

METRO_KEYWORDS = [
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
]

_JOSA = sorted([
    "으로부터", "에게서", "에서부터", "로부터",
    "에서", "에게", "한테", "으로", "까지", "부터", "처럼", "만큼", "보다",
    "에", "의", "을", "를", "이", "가", "은", "는", "과", "와", "도", "만", "로", "야", "아",
], key=len, reverse=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("benefic.policy_search")


def _extract_field_from_text(text: str, field: str) -> str:
    m = _re.search(rf"{field}:\s*(.+?)(?:\n|$)", str(text or ""))
    return m.group(1).strip() if m else ""


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in str(text or "").split():
        if len(word) < 2:
            continue
        tokens.append(word)
        for josa in _JOSA:
            if word.endswith(josa) and len(word) - len(josa) >= 2:
                tokens.append(word[:-len(josa)])
                break
    return tokens


# ──────────────────────────────────────────────
# 1. 사용자 정보 → 검색 쿼리 변환
# ──────────────────────────────────────────────
def build_query(user: dict) -> str:
    base_parts = []

    age = user.get("나이")
    if age:
        base_parts.append(f"{age}세")

    family = user.get("가구유형", "")
    if family:
        base_parts.append(family)

    emp = user.get("고용상태", "")
    if emp:
        base_parts.append(emp)

    income = user.get("연소득")
    if income is not None and income > 0:
        base_parts.append(f"연소득 {income}만원")

    region = user.get("거주지역", "")
    if region and region != "전국":
        base_parts.append(f"{region} 거주")

    disability = user.get("장애여부", "없음")
    if disability and disability != "없음":
        base_parts.append(disability)

    if user.get("국가유공자"):
        base_parts.append("국가유공자")

    if user.get("다문화가구"):
        base_parts.append("다문화 가구")

    base = " ".join(base_parts)

    parts = []
    parts.append(f"[서비스] {base}")
    parts.append(f"[목적] {base}")
    parts.extend([f"[지원내용] {base}"] * 2)
    parts.extend([f"[대상] {base}"] * 3)
    parts.extend([f"[선정기준] {base}"] * 2)

    query = " ".join(parts)
    log.info("검색 쿼리: %s", query)
    return query


class HybridSearcher:
    """Chroma + BM25 하이브리드 검색기"""

    _instance: "HybridSearcher | None" = None

    def __new__(cls) -> "HybridSearcher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self) -> None:
        if self._loaded:
            return

        if not CHROMA_PATH.exists():
            raise FileNotFoundError(
                "chroma_db 폴더가 없습니다.\n"
                "종민님이 공유한 chroma_db 폴더를 프로젝트 루트에 두세요."
            )
        if not WELFARE_CHUNKS_PATH.exists():
            raise FileNotFoundError(
                "data/processed/chunks.csv 파일이 없습니다.\n"
                "종민님이 공유한 data 폴더를 프로젝트 루트에 두세요."
            )

        client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.collection = client.get_collection(COLLECTION_NAME)

        chunk_frames = [pd.read_csv(WELFARE_CHUNKS_PATH)]
        if GOV24_CHUNKS_PATH.exists():
            chunk_frames.append(pd.read_csv(GOV24_CHUNKS_PATH))
        self.df_chunks = pd.concat(chunk_frames, ignore_index=True)
        self.df_chunks["chunk_id"] = self.df_chunks["chunk_id"].astype(str)
        self.df_chunks["policy_id"] = self.df_chunks["policy_id"].astype(str)
        self.df_chunks = self.df_chunks.set_index("chunk_id", drop=False)

        log.info("전체 청크 로드: %d개", len(self.df_chunks))
        self.model = SentenceTransformer(MODEL_NAME)
        self.chunk_ids = self.df_chunks["chunk_id"].tolist()
        self.bm25 = BM25Okapi([tokenize(text) for text in self.df_chunks["text"].tolist()])

        self._loaded = True
        log.info("하이브리드 검색기 준비 완료")

    def _normalize_chunk_id(self, chunk_id: str) -> str | None:
        cid = str(chunk_id)
        if cid in self.df_chunks.index:
            return cid
        suffixed = f"{cid}_01"
        if suffixed in self.df_chunks.index:
            return suffixed
        return None

    def vector_search(self, query: str, top_k: int = 10) -> dict[str, float]:
        self._load()
        query_embedding = self.model.encode([query], normalize_embeddings=True).tolist()
        results = self.collection.query(query_embeddings=query_embedding, n_results=top_k)

        scores: dict[str, float] = {}
        for raw_id, dist in zip(results["ids"][0], results["distances"][0]):
            normalized_id = self._normalize_chunk_id(raw_id)
            if normalized_id is None:
                continue
            scores[normalized_id] = 1 - float(dist)
        return scores

    def bm25_search(self, query: str) -> dict[str, float]:
        self._load()
        scores = self.bm25.get_scores(tokenize(query))
        max_score = max(scores) + 1e-9
        normalized = scores / max_score
        return {chunk_id: float(normalized[i]) for i, chunk_id in enumerate(self.chunk_ids)}

    def search(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        alpha: float = ALPHA_DEFAULT,
        filters: dict[str, str] | None = None,
    ) -> list[dict]:
        self._load()

        vector_scores = self.vector_search(query, top_k=top_k * 3)
        bm25_scores = self.bm25_search(query)

        all_ids = set(vector_scores.keys()) | set(bm25_scores.keys())
        final_scores = {
            cid: alpha * vector_scores.get(cid, 0.0) + (1 - alpha) * bm25_scores.get(cid, 0.0)
            for cid in all_ids
        }

        top_ids = sorted(final_scores, key=final_scores.get, reverse=True)

        results: list[dict] = []
        seen_names: set[str] = set()
        for chunk_id in top_ids:
            row = self.df_chunks.loc[chunk_id]
            text_val = str(row["text"])

            item = {
                "chunk_id": chunk_id,
                "policy_id": str(row["policy_id"]),
                "서비스명": row["policy_name"],
                "policy_name": row["policy_name"],
                "서비스분야": row["category"],
                "category": row["category"],
                "소관기관명": _extract_field_from_text(text_val, "소관기관") or _extract_field_from_text(text_val, "소관부처") or row["category"],
                "소관조직명": _extract_field_from_text(text_val, "소관조직"),
                "지원유형": _extract_field_from_text(text_val, "지원유형"),
                "지원대상": _extract_field_from_text(text_val, "지원대상"),
                "지원내용": _extract_field_from_text(text_val, "지원내용") or _extract_field_from_text(text_val, "서비스요약"),
                "선정기준": _extract_field_from_text(text_val, "선정기준"),
                "신청방법": _extract_field_from_text(text_val, "신청방법"),
                "신청기한": _extract_field_from_text(text_val, "신청기한"),
                "전화문의": _extract_field_from_text(text_val, "전화문의") or _extract_field_from_text(text_val, "대표문의"),
                "상세조회url": row["source_url"],
                "source_url": row["source_url"],
                "region": row["region"],
                "score": round(final_scores[chunk_id], 4),
                "vector_score": round(vector_scores.get(chunk_id, 0.0), 4),
                "bm25_score": round(bm25_scores.get(chunk_id, 0.0), 4),
                "evidence_text": text_val,
            }

            if filters and not self._match(item, filters):
                continue

            name = str(item.get("서비스명") or chunk_id)
            if name in seen_names:
                continue
            seen_names.add(name)
            results.append(item)

            if len(results) >= top_k:
                break

        return results

    @staticmethod
    def _match(item: dict, filters: dict[str, str]) -> bool:
        for col, val in filters.items():
            if str(val).lower() not in str(item.get(col, "")).lower():
                return False
        return True


# ──────────────────────────────────────────────
# 3. 공개 인터페이스
# ──────────────────────────────────────────────
def search_by_keyword(
    keyword: str = "",
    category: str = "",
    support_type: str = "",
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    engine = create_engine(DB_URL)
    conditions, params = ["1=1"], {}

    if keyword:
        conditions.append("(서비스명 LIKE :kw OR 지원내용 LIKE :kw OR 서비스목적요약 LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    if category:
        conditions.append("서비스분야 LIKE :cat")
        params["cat"] = f"%{category}%"
    if support_type:
        conditions.append("지원유형 LIKE :stype")
        params["stype"] = f"%{support_type}%"

    sql = (
        f"SELECT * FROM {TABLE_NAME} WHERE {' AND '.join(conditions)}"
        f" ORDER BY 서비스명 LIMIT :lim OFFSET :off"
    )
    params["lim"] = limit
    params["off"] = offset

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(sql), params).fetchall()
        results = [dict(r._mapping) for r in rows]
        log.info("키워드 검색: '%s' → %d 건", keyword, len(results))
        return results
    except Exception as e:
        log.error("키워드 검색 오류: %s", e)
        return []


def search_by_natural_language(query_text: str, top_k: int = TOP_K_DEFAULT) -> list[dict]:
    if not query_text.strip():
        return []
    results = HybridSearcher().search(query_text.strip(), top_k=top_k)
    log.info("자연어 검색: '%s' → %d 건", query_text[:30], len(results))
    return results


def browse_all(
    page: int = 1,
    per_page: int = 20,
    category: str = "",
    sort_by: str = "서비스명",
) -> dict:
    engine = create_engine(DB_URL)
    offset = (page - 1) * per_page
    where = "WHERE 서비스분야 LIKE :cat" if category else ""
    params: dict = {}
    if category:
        params["cat"] = f"%{category}%"

    try:
        with engine.connect() as conn:
            total_row = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE_NAME} {where}"), params).fetchone()
            total = total_row[0] if total_row else 0

            rows = conn.execute(
                text(
                    f"SELECT * FROM {TABLE_NAME} {where}"
                    f" ORDER BY {sort_by} LIMIT :lim OFFSET :off"
                ),
                {**params, "lim": per_page, "off": offset},
            ).fetchall()

        results = [dict(r._mapping) for r in rows]
        total_pages = -(-total // per_page)
        log.info("전체 브라우징: page=%d/%d, %d 건", page, total_pages, len(results))
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "results": results,
        }
    except Exception as e:
        log.error("브라우징 오류: %s", e)
        return {"total": 0, "page": page, "per_page": per_page, "total_pages": 0, "results": []}


def get_categories() -> list[str]:
    engine = create_engine(DB_URL)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT 서비스분야 FROM {TABLE_NAME} WHERE 서비스분야 IS NOT NULL ORDER BY 서비스분야")
            ).fetchall()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        log.error("카테고리 조회 오류: %s", e)
        return []


def search_policies(
    user: dict | None = None,
    query_text: str = "",
    top_k: int = TOP_K_DEFAULT,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    if user:
        query = build_query(user)
    elif query_text:
        query = query_text
    else:
        return []

    results = HybridSearcher().search(query, top_k=top_k, filters=filters)

    results = [r for r in results if "마감" not in str(r.get("서비스명") or "")]

    region = (user or {}).get("거주지역", "")
    if region and region != "전국":
        user_region_kw = next((kw for kw in METRO_KEYWORDS if kw in region), None)

        def is_allowed(r: dict) -> bool:
            target = str(r.get("소관기관명") or "") + str(r.get("서비스명") or "")
            for kw in METRO_KEYWORDS:
                if kw == user_region_kw:
                    continue
                if kw in target:
                    return False
            return True

        results = [r for r in results if is_allowed(r)]

    log.info("검색 결과: %d 건 (마감·지역 필터 후)", len(results))
    return results
