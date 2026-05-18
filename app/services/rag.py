from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import time


logger = logging.getLogger(__name__)
RAG_CACHE_TTL_SECONDS = 20
_RAG_CACHE: dict[str, tuple[float, "RagSearchResult"]] = {}


@dataclass
class RagSearchResult:
    success: bool
    answer: str | None
    docs_used: list[str]


def normalize_reference(item: object) -> str | None:
    if isinstance(item, dict):
        for key in ("policy_id", "source_policy_id", "reference_id", "id"):
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return None
    if item is None:
        return None
    value = str(item).strip()
    return value or None


def _rag_cache_key(*, query: str, user_condition: dict[str, object], lang_code: str) -> str:
    return json.dumps(
        {
            "query": query,
            "user_condition": user_condition,
            "lang_code": lang_code,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def search_rag(*, query: str, user_condition: dict[str, object], lang_code: str = "ko") -> RagSearchResult:
    cache_key = _rag_cache_key(query=query, user_condition=user_condition, lang_code=lang_code)
    cached = _RAG_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached[0]) < RAG_CACHE_TTL_SECONDS:
        return cached[1]

    try:
        from rag.pipeline import benepick_rag

        payload = benepick_rag(
            user_query=query,
            user_condition=user_condition,
            lang_code=lang_code,
        )
    except Exception as exc:
        logger.exception("RAG function call failed: %s", exc)
        result = RagSearchResult(success=False, answer=None, docs_used=[])
        _RAG_CACHE[cache_key] = (now, result)
        return result

    data = payload.get("data") or {}
    docs_used = []
    for item in data.get("docs_used") or []:
        reference = normalize_reference(item)
        if reference:
            docs_used.append(reference)
    result = RagSearchResult(
        success=bool(payload.get("success")),
        answer=data.get("answer"),
        docs_used=docs_used,
    )
    _RAG_CACHE[cache_key] = (time.time(), result)
    return result
