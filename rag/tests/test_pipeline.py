"""
benepick RAG 파이프라인 단위 테스트
실행: pytest tests/test_pipeline.py -v
"""
import sys
from unittest.mock import MagicMock, patch, call
import pytest

# ─────────────────────────────────────────────────────────────────
# 무거운 의존성을 import 전에 Mock 처리 (GPU/ChromaDB/LLM 불필요)
# ─────────────────────────────────────────────────────────────────
_mock_modules = [
    "chromadb", "rank_bm25", "sentence_transformers",
    "FlagEmbedding", "langchain_ollama",
    "langchain_core", "langchain_core.messages",
    "dotenv", "pandas",
]
for _mod in _mock_modules:
    sys.modules.setdefault(_mod, MagicMock())

# searcher 모듈 Mock (HybridSearcher 생성자 포함)
_mock_searcher_instance = MagicMock()
_mock_searcher_module = MagicMock()
_mock_searcher_module.HybridSearcher = MagicMock(return_value=_mock_searcher_instance)
sys.modules["searcher"] = _mock_searcher_module

# pipeline 임포트 (무거운 모듈 없이 가능)
import pipeline

# 모듈 레벨 전역 객체 교체
_mock_reranker = MagicMock()
_mock_llm = MagicMock()
pipeline.searcher = _mock_searcher_instance
pipeline.reranker = _mock_reranker
pipeline.llm = _mock_llm


# ─────────────────────────────────────────────────────────────────
# 공통 샘플 데이터
# ─────────────────────────────────────────────────────────────────
def make_doc(policy_id="101", chunk_id="101_01", policy_name="청년 월세 지원",
             score=0.85, evidence_text="청년 1인 가구에게 월세를 지원합니다.", rank=1):
    return {
        "rank":          rank,
        "chunk_id":      chunk_id,
        "policy_id":     policy_id,
        "policy_name":   policy_name,
        "category":      "주거",
        "region":        "서울",
        "source_url":    "https://example.com",
        "score":         score,
        "vector_score":  0.9,
        "bm25_score":    0.75,
        "evidence_text": evidence_text,
    }


SAMPLE_DOCS = [
    make_doc("101", "101_01", "청년 월세 지원",     score=0.85, rank=1),
    make_doc("102", "102_01", "청년 고용 지원",     score=0.80, rank=2),
    make_doc("103", "103_01", "기초생활수급자 지원", score=0.75, rank=3),
]


# ═════════════════════════════════════════════════════════════════
# 1. 응답 형식 헬퍼
# ═════════════════════════════════════════════════════════════════
class TestResponseHelpers:
    def test_success_response_has_required_keys(self):
        result = pipeline.success_response({"answer": "테스트 답변"})
        assert result["success"] is True
        assert "data" in result
        assert "timestamp" in result

    def test_success_response_data_passthrough(self):
        data = {"query": "청년 지원", "answer": "월세 지원 있습니다."}
        result = pipeline.success_response(data)
        assert result["data"] == data

    def test_success_response_timestamp_format(self):
        import re
        result = pipeline.success_response({})
        # ISO 8601 기본 형식: YYYY-MM-DDTHH:MM:SS
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", result["timestamp"])

    def test_error_response_has_required_keys(self):
        result = pipeline.error_response("SEARCH_FAILED", "검색 실패")
        assert result["success"] is False
        assert result["error_code"] == "SEARCH_FAILED"
        assert result["error_message"] == "검색 실패"
        assert "timestamp" in result

    def test_error_response_success_is_false(self):
        result = pipeline.error_response("ANY_CODE", "any message")
        assert result["success"] is False

    def test_success_and_error_have_different_success_flag(self):
        s = pipeline.success_response({})
        e = pipeline.error_response("CODE", "msg")
        assert s["success"] != e["success"]


# ═════════════════════════════════════════════════════════════════
# 2. is_complex (복잡한 질문 판단)
# ═════════════════════════════════════════════════════════════════
class TestIsComplex:
    def test_complex_query_with_long_text_and_many_keywords(self):
        # 길이 > 15, 복지 키워드 2개 이상
        assert pipeline.is_complex("서울 청년 소득 기준 주거 지원 신청 방법") is True

    def test_short_query_is_not_complex(self):
        # 길이 <= 15
        assert pipeline.is_complex("청년 지원") is False

    def test_long_query_with_few_keywords_is_not_complex(self):
        # 길이 > 15, 키워드 1개
        assert pipeline.is_complex("안녕하세요 오늘 날씨가 정말 맑고 청명합니다") is False

    def test_long_query_with_two_keywords_is_complex(self):
        assert pipeline.is_complex("청년 소득 조건에 맞는 지원 프로그램을 찾고 있습니다") is True

    def test_empty_query_is_not_complex(self):
        assert pipeline.is_complex("") is False


# ═════════════════════════════════════════════════════════════════
# 3. relax_query (조건 완화)
# ═════════════════════════════════════════════════════════════════
class TestRelaxQuery:
    def test_removes_city_name(self):
        result = pipeline.relax_query("서울 청년 월세 지원")
        assert "서울" not in result
        assert "청년" in result

    def test_removes_household_size(self):
        result = pipeline.relax_query("1인 가구 청년 지원")
        assert "1인" not in result
        assert "가구" not in result

    def test_removes_multiple_stopwords(self):
        result = pipeline.relax_query("부산 2인 가구 청년 지원")
        assert "부산" not in result
        assert "2인" not in result
        assert "가구" not in result

    def test_no_stopwords_unchanged(self):
        query = "취업 준비생 훈련비 지원"
        result = pipeline.relax_query(query)
        assert result == query

    def test_result_has_no_extra_spaces(self):
        result = pipeline.relax_query("서울 청년 1인 가구 지원")
        assert "  " not in result  # 연속 공백 없음


# ═════════════════════════════════════════════════════════════════
# 4. get_category_query (카테고리 매핑)
# ═════════════════════════════════════════════════════════════════
class TestGetCategoryQuery:
    @pytest.mark.parametrize("query,expected_category", [
        ("청년 월세 지원",     "청년 주거 지원"),
        ("전세 사기 피해자",   "청년 주거 지원"),
        ("취업 지원 프로그램", "청년 고용 지원"),
        ("실업급여 신청",      "청년 고용 지원"),
        ("생계급여 기준",      "저소득 생활 지원"),
        ("의료비 지원",        "의료비 지원"),
        ("출산 지원금",        "출산 육아 지원"),
        ("육아휴직 급여",      "출산 육아 지원"),
        ("노인 돌봄 서비스",   "노인 복지 지원"),
        ("장애인 활동 지원",   "장애인 복지 지원"),
    ])
    def test_keyword_to_category(self, query, expected_category):
        assert pipeline.get_category_query(query) == expected_category

    def test_no_matching_keyword_returns_original(self):
        query = "외국어 교육 지원"
        assert pipeline.get_category_query(query) == query

    def test_empty_query_returns_empty(self):
        assert pipeline.get_category_query("") == ""


# ═════════════════════════════════════════════════════════════════
# 5. rerank (재정렬)
# ═════════════════════════════════════════════════════════════════
class TestRerank:
    def setup_method(self):
        _mock_reranker.reset_mock()

    def test_returns_top_k_results(self):
        _mock_reranker.compute_score.return_value = [0.9, 0.5, 0.3]
        results = rerank_with_reset([make_doc(score=0.8)] * 3, top_k=2)
        assert len(results) == 2

    def test_sorts_by_score_descending(self):
        _mock_reranker.compute_score.return_value = [0.3, 0.9, 0.5]
        docs = [
            make_doc("101", "101_01", score=0.8, rank=1),
            make_doc("102", "102_01", score=0.7, rank=2),
            make_doc("103", "103_01", score=0.6, rank=3),
        ]
        results = pipeline.rerank("청년 지원", docs, top_k=3)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_score_updated_to_reranker_score(self):
        _mock_reranker.compute_score.return_value = [0.777]
        docs = [make_doc(score=0.1)]
        results = pipeline.rerank("청년 지원", docs, top_k=1)
        assert results[0]["score"] == pytest.approx(0.777, abs=0.001)

    def test_empty_results_returns_empty(self):
        results = pipeline.rerank("청년 지원", [], top_k=5)
        assert results == []
        _mock_reranker.compute_score.assert_not_called()

    def test_calls_reranker_with_correct_pairs(self):
        _mock_reranker.compute_score.return_value = [0.5]
        query = "청년 지원"
        doc = make_doc(evidence_text="청년 지원 내용입니다.")
        pipeline.rerank(query, [doc], top_k=1)
        expected_pairs = [[query, "청년 지원 내용입니다."]]
        _mock_reranker.compute_score.assert_called_once_with(expected_pairs, normalize=True)


def rerank_with_reset(docs, top_k=5):
    """rerank 호출 편의 함수"""
    return pipeline.rerank("청년 지원", docs, top_k=top_k)


# ═════════════════════════════════════════════════════════════════
# 6. crag_quality_check (품질 검증 3단계 분기)
# ═════════════════════════════════════════════════════════════════
class TestCragQualityCheck:
    def setup_method(self):
        _mock_searcher_instance.reset_mock()
        _mock_reranker.reset_mock()

    def _make_docs_with_score(self, score, count=3):
        return [make_doc(score=score, rank=i+1) for i in range(count)]

    def test_high_quality_returns_original_results(self):
        """score 평균 >= 0.7 → 원본 반환"""
        docs = self._make_docs_with_score(0.8)
        result = pipeline.crag_quality_check("청년 지원", docs)
        assert result == docs
        _mock_searcher_instance.search.assert_not_called()

    def test_medium_quality_triggers_relaxed_search(self):
        """score 평균 0.4~0.7 → 완화 쿼리 재검색"""
        docs = self._make_docs_with_score(0.5)
        relaxed_docs = [make_doc(score=0.6)] * 3
        _mock_searcher_instance.search.return_value = relaxed_docs
        _mock_reranker.compute_score.return_value = [0.6] * len(relaxed_docs)

        pipeline.crag_quality_check("서울 청년 지원", docs)
        _mock_searcher_instance.search.assert_called_once()

    def test_low_quality_triggers_fallback(self):
        """score 평균 < 0.4 → 카테고리 폴백"""
        docs = self._make_docs_with_score(0.2)
        fallback_docs = [make_doc(score=0.5)] * 2
        _mock_searcher_instance.search.return_value = fallback_docs

        result = pipeline.crag_quality_check("월세 지원", docs)
        _mock_searcher_instance.search.assert_called_once()
        # 폴백 쿼리로 검색했어야 함
        called_query = _mock_searcher_instance.search.call_args[0][0]
        assert called_query == "청년 주거 지원"  # get_category_query("월세 지원")

    def test_empty_results_triggers_fallback(self):
        """빈 결과 → 폴백 실행"""
        fallback_docs = [make_doc(score=0.5)]
        _mock_searcher_instance.search.return_value = fallback_docs
        pipeline.crag_quality_check("청년 지원", [])
        _mock_searcher_instance.search.assert_called_once()

    def test_medium_quality_uses_relaxed_query(self):
        """조건 완화 시 도시명/가구수 제거된 쿼리 사용"""
        docs = self._make_docs_with_score(0.5)
        _mock_searcher_instance.search.return_value = [make_doc(score=0.6)]
        _mock_reranker.compute_score.return_value = [0.6]

        pipeline.crag_quality_check("서울 1인 가구 청년 지원", docs)
        called_query = _mock_searcher_instance.search.call_args[0][0]
        assert "서울" not in called_query
        assert "1인" not in called_query


# ═════════════════════════════════════════════════════════════════
# 7. generate_answer (LLM 답변 생성)
# ═════════════════════════════════════════════════════════════════
class TestGenerateAnswer:
    def setup_method(self):
        _mock_llm.reset_mock()
        # SystemMessage / HumanMessage 생성자 호출 기록 초기화
        sys.modules["langchain_core.messages"].SystemMessage.reset_mock()
        sys.modules["langchain_core.messages"].HumanMessage.reset_mock()

    def _mock_llm_response(self, content: str):
        mock_response = MagicMock()
        mock_response.content = content
        _mock_llm.invoke.return_value = mock_response

    def _get_system_content(self) -> str:
        """SystemMessage(content=...) 에 실제로 전달된 content 문자열 반환"""
        mock_sys_msg = sys.modules["langchain_core.messages"].SystemMessage
        return mock_sys_msg.call_args[1]["content"]

    def _get_human_content(self) -> str:
        """HumanMessage(content=...) 에 실제로 전달된 content 문자열 반환"""
        mock_human_msg = sys.modules["langchain_core.messages"].HumanMessage
        return mock_human_msg.call_args[1]["content"]

    def test_returns_llm_content(self):
        self._mock_llm_response("청년 월세 지원 정책이 있습니다.")
        result = pipeline.generate_answer("청년 지원", SAMPLE_DOCS)
        assert result == "청년 월세 지원 정책이 있습니다."

    def test_calls_llm_invoke_once(self):
        self._mock_llm_response("답변입니다.")
        pipeline.generate_answer("청년 지원", SAMPLE_DOCS)
        _mock_llm.invoke.assert_called_once()

    def test_lang_code_ko_in_prompt(self):
        self._mock_llm_response("답변")
        pipeline.generate_answer("청년 지원", SAMPLE_DOCS, lang_code="ko")
        assert "한국어" in self._get_system_content()

    def test_lang_code_en_in_prompt(self):
        self._mock_llm_response("answer")
        pipeline.generate_answer("youth support", SAMPLE_DOCS, lang_code="en")
        assert "English" in self._get_system_content()

    def test_policy_names_included_in_prompt(self):
        self._mock_llm_response("답변")
        pipeline.generate_answer("청년 지원", SAMPLE_DOCS)
        human_content = self._get_human_content()
        for doc in SAMPLE_DOCS:
            assert doc["policy_name"] in human_content

    def test_unsupported_lang_code_falls_back_to_korean(self):
        self._mock_llm_response("답변")
        pipeline.generate_answer("청년 지원", SAMPLE_DOCS, lang_code="ja")
        assert "한국어" in self._get_system_content()


# ═════════════════════════════════════════════════════════════════
# 8. benepick_rag (메인 파이프라인 통합 테스트)
# ═════════════════════════════════════════════════════════════════
class TestBenepickRag:
    def setup_method(self):
        _mock_searcher_instance.reset_mock()
        _mock_reranker.reset_mock()
        _mock_llm.reset_mock()

        # side_effect 잔류 방지 (이전 테스트에서 exception을 주입한 경우)
        _mock_searcher_instance.search.side_effect = None
        _mock_reranker.compute_score.side_effect = None
        _mock_llm.invoke.side_effect = None

        # 기본 Mock 반환값 설정
        _mock_searcher_instance.search.return_value = SAMPLE_DOCS
        _mock_reranker.compute_score.return_value = [0.85, 0.80, 0.75]
        mock_resp = MagicMock()
        mock_resp.content = "청년 월세 지원 정책이 있습니다."
        _mock_llm.invoke.return_value = mock_resp

    def test_success_response_structure(self):
        result = pipeline.benepick_rag("청년 월세 지원")
        assert result["success"] is True
        assert "data" in result
        assert "timestamp" in result

    def test_data_contains_required_fields(self):
        result = pipeline.benepick_rag("청년 월세 지원")
        data = result["data"]
        assert "query" in data
        assert "answer" in data
        assert "lang_code" in data
        assert "docs_used" in data
        assert "doc_count" in data
        assert "search_time_ms" in data

    def test_query_passthrough(self):
        query = "청년 월세 지원"
        result = pipeline.benepick_rag(query)
        assert result["data"]["query"] == query

    def test_lang_code_default_is_ko(self):
        result = pipeline.benepick_rag("청년 지원")
        assert result["data"]["lang_code"] == "ko"

    def test_lang_code_en_passthrough(self):
        result = pipeline.benepick_rag("youth support", lang_code="en")
        assert result["data"]["lang_code"] == "en"

    def test_user_condition_passthrough(self):
        condition = {"age": 28, "income": "low", "region": "서울"}
        result = pipeline.benepick_rag("청년 지원", user_condition=condition)
        assert result["data"]["user_condition"] == condition

    def test_user_condition_none_by_default(self):
        result = pipeline.benepick_rag("청년 지원")
        assert result["data"]["user_condition"] is None

    def test_docs_used_structure(self):
        result = pipeline.benepick_rag("청년 지원")
        for doc in result["data"]["docs_used"]:
            assert "policy_id"   in doc
            assert "chunk_id"    in doc
            assert "policy_name" in doc
            assert "score"       in doc
            assert "rank"        in doc

    def test_doc_count_matches_docs_used_length(self):
        result = pipeline.benepick_rag("청년 지원")
        assert result["data"]["doc_count"] == len(result["data"]["docs_used"])

    def test_search_time_ms_is_non_negative_int(self):
        result = pipeline.benepick_rag("청년 지원")
        search_time = result["data"]["search_time_ms"]
        assert isinstance(search_time, int)
        assert search_time >= 0

    def test_score_in_docs_is_float_0_to_1(self):
        result = pipeline.benepick_rag("청년 지원")
        for doc in result["data"]["docs_used"]:
            assert 0.0 <= doc["score"] <= 1.0

    def test_error_when_no_search_results(self):
        _mock_searcher_instance.search.return_value = []
        result = pipeline.benepick_rag("알 수 없는 질문")
        assert result["success"] is False
        assert result["error_code"] == "SEARCH_FAILED"

    def test_error_on_searcher_exception(self):
        _mock_searcher_instance.search.side_effect = RuntimeError("ChromaDB 연결 실패")
        result = pipeline.benepick_rag("청년 지원")
        assert result["success"] is False
        assert result["error_code"] == "SEARCH_FAILED"
        assert "ChromaDB 연결 실패" in result["error_message"]

    def test_error_on_llm_exception(self):
        _mock_llm.invoke.side_effect = RuntimeError("LLM 타임아웃")
        result = pipeline.benepick_rag("청년 지원")
        assert result["success"] is False

    def test_searcher_called_with_correct_alpha(self):
        pipeline.benepick_rag("청년 지원")
        call_kwargs = _mock_searcher_instance.search.call_args
        assert call_kwargs[1]["alpha"] == 0.6

    def test_searcher_called_with_correct_top_k(self):
        pipeline.benepick_rag("청년 지원")
        call_kwargs = _mock_searcher_instance.search.call_args
        assert call_kwargs[1]["top_k"] == 25

    def test_pipeline_calls_reranker(self):
        pipeline.benepick_rag("청년 지원")
        _mock_reranker.compute_score.assert_called()

    def test_pipeline_calls_llm(self):
        pipeline.benepick_rag("청년 지원")
        _mock_llm.invoke.assert_called_once()
