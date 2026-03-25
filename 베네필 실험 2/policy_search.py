"""
06 유사 정책 검색
=================
사용자 정보 → 검색 쿼리 생성 → FAISS 유사도 검색 → Top-K 정책 반환

수정 사항:
  - [BUG FIX] SCORE_MIN 0.3 → 0.45 상향 (너무 낮으면 무관한 정책 다수 반환)
  - 검색 쿼리 품질 개선: 조건 없는 필드는 제외, 유의미한 키워드 조합만 사용
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
MODEL_NAME = "BAAI/bge-m3"
INDEX_DIR  = Path("faiss_index")
INDEX_PATH = INDEX_DIR / "gov_benefits.index"
META_PATH  = INDEX_DIR / "metadata.json"

TOP_K_DEFAULT = 10
SCORE_MIN     = 0.45  # [수정] 0.3 → 0.45: 너무 낮으면 무관한 정책 다수 포함

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("benefic.policy_search")


# ──────────────────────────────────────────────
# 1. 사용자 정보 → 검색 쿼리 변환
# ──────────────────────────────────────────────
def build_query(user: dict) -> str:
    """
    사용자 정보 dict → 자연어 검색 쿼리 생성
    정책 필드 형식([지원내용]×2, [대상]×3, [선정기준]×2)에 맞춰 가중치 적용
    """
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

    # 정책 필드 가중치에 맞춰 쿼리 구성
    # 서비스명×1, 목적요약×1, 지원내용×2, 지원대상×3, 선정기준×2
    parts = []
    parts.append(f"[서비스] {base}")
    parts.append(f"[목적] {base}")
    parts.extend([f"[지원내용] {base}"] * 2)
    parts.extend([f"[대상] {base}"] * 3)
    parts.extend([f"[선정기준] {base}"] * 2)

    query = " ".join(parts)
    log.info("검색 쿼리: %s", query)
    return query


# ──────────────────────────────────────────────
# 2. FAISS 검색기
# ──────────────────────────────────────────────
class PolicySearcher:
    """FAISS 기반 정책 유사도 검색기 (싱글턴 — 모델을 한 번만 로드)"""

    _instance: "PolicySearcher | None" = None

    def __new__(cls) -> "PolicySearcher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def _load(self) -> None:
        if self._loaded:
            return

        if not INDEX_PATH.exists() or not META_PATH.exists():
            raise FileNotFoundError(
                "FAISS 인덱스가 없습니다.\n"
                "먼저 실행하세요: python gov_benefits_embedding.py --once"
            )

        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"

        log.info("모델 로드 중: %s (%s)", MODEL_NAME, device)
        self.model = SentenceTransformer(MODEL_NAME, device=device)
        self.index = faiss.read_index(str(INDEX_PATH))
        self.meta  = json.loads(META_PATH.read_text(encoding="utf-8"))
        self._loaded = True
        log.info("검색기 준비 완료 — 총 %d 개 정책", self.index.ntotal)

    def search(
        self,
        query: str,
        top_k: int = TOP_K_DEFAULT,
        score_min: float = SCORE_MIN,
        filters: dict[str, str] | None = None,
    ) -> list[dict]:
        self._load()

        q_vec = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype(np.float32)

        fetch_k = min(top_k * 10 if filters else top_k * 3, self.index.ntotal)
        scores, indices = self.index.search(q_vec, fetch_k)

        results = []
        seen_names = set()  # 서비스명 중복 제거
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or float(score) < score_min:
                continue

            item = self.meta[idx].copy()
            item["score"] = round(float(score), 4)

            if filters and not self._match(item, filters):
                continue

            # 서비스명 기준 중복 제거
            name = item.get("서비스명") or str(idx)
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
            if val.lower() not in (item.get(col) or "").lower():
                return False
        return True


# ──────────────────────────────────────────────
# 3. 공개 인터페이스
# ──────────────────────────────────────────────
def search_policies(
    user: dict,
    top_k: int = TOP_K_DEFAULT,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    """
    사용자 정보 dict → 유사 정책 리스트 반환

    Parameters
    ----------
    user    : get_user_input() 반환값
    top_k   : 반환 건수 (기본 10)
    filters : 추가 필터 ex) {"지원유형": "현금지원"}
    """
    query   = build_query(user)
    results = PolicySearcher().search(query, top_k=top_k, filters=filters)

    # 서비스명에 '마감' 포함된 항목 제외
    results = [r for r in results if "마감" not in (r.get("서비스명") or "")]

    # 지역 필터: 전국 정책 + 본인 거주지역 정책만 포함
    region = user.get("거주지역", "")
    if region and region != "전국":
        METRO_KEYWORDS = [
            "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
            "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"
        ]
        user_region_kw = next((kw for kw in METRO_KEYWORDS if kw in region), None)

        def is_allowed(r: dict) -> bool:
            target = (r.get("소관기관명") or "") + (r.get("서비스명") or "")
            for kw in METRO_KEYWORDS:
                if kw == user_region_kw:
                    continue
                if kw in target:
                    return False
            return True

        results = [r for r in results if is_allowed(r)]

    log.info("검색 결과: %d 건 (마감·지역 필터 후)", len(results))
    return results


# ──────────────────────────────────────────────
# 4. 결과 출력 유틸
# ──────────────────────────────────────────────
def print_results(results: list[dict]) -> None:
    if not results:
        print("\n검색 결과가 없습니다.")
        return

    print(f"\n{'─' * 60}")
    print(f"  검색 결과 {len(results)}건")
    print(f"{'─' * 60}")

    for i, r in enumerate(results, 1):
        print(f"\n[{i}] {r.get('서비스명', '-')}  (유사도: {r['score']:.4f})")
        print(f"    분야  : {r.get('서비스분야', '-')}")
        print(f"    유형  : {r.get('지원유형', '-')}")
        print(f"    기관  : {r.get('소관기관명', '-')}")
        print(f"    기한  : {r.get('신청기한', '-')}")
        if r.get('지원대상'):
            print(f"    지원대상: {r['지원대상']}")
        print(f"    신청  : {r.get('신청방법', '-')}")
        print(f"    접수  : {r.get('접수기관', '-')}")
        print(f"    문의  : {r.get('전화문의', '-')}")
        if r.get("상세조회url"):
            print(f"    URL   : {r['상세조회url']}")

    print(f"\n{'─' * 60}\n")


# ──────────────────────────────────────────────
# 5. 단독 실행
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from user_input import get_user_input

    # 키 목록 확인 모드: python policy_search.py --keys
    if "--keys" in sys.argv:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        if meta:
            print("metadata.json 첫 번째 항목 키 목록:")
            for k, v in meta[0].items():
                print(f"  {k!r}: {v!r}")
        sys.exit(0)

    user    = get_user_input()
    results = search_policies(user, top_k=10)
    print_results(results)
