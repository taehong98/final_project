# 베네픽 (BenePick) RAG 파이프라인 — 프로젝트 가이드

> 이 문서는 Claude Code가 프로젝트를 이해하고 올바르게 작업하기 위한 핵심 가이드입니다.
> 코드 수정 전 반드시 전체를 읽으세요.

---

## 1. 프로젝트 개요

**베네픽(BenePick)** 은 한국 복지 정책 검색 RAG 시스템입니다.
사용자가 자연어로 복지 정책을 질문하면, RAG 파이프라인이 관련 정책을 검색하고 LLM이 답변을 생성합니다.

- **부트캠프**: 구름(Goorm) 생성형 AI 개발자 과정 7기
- **팀**: 2팀 (5인)
- **GitHub**: `github.com/taehong98/final_project` (RAG 브랜치)

---

## 2. 팀 구성 및 역할

| 이름 | 역할 | 담당 |
|------|------|------|
| 박종민 (Daniel) | RAG 파이프라인 팀장 | 데이터 수집, 임베딩, 검색, 평가, FastAPI 연결 |
| 최태홍 | 백엔드 | FastAPI 서버, DB(PostgreSQL), API 엔드포인트 |
| 고준 | 데이터/평가 | Ragas 평가 (박종민이 대신 진행 중) |
| 남정현 | 프론트엔드 | React/Next.js UI |
| 최은철 | 프롬프트/sLLM | 프롬프트 엔지니어링, sLLM 파인튜닝 |

---

## 3. 데이터 현황

| 출처 | 건수 | 파일 |
|------|------|------|
| 복지로 API | 367건 | `data/raw/welfare_policies.csv` |
| 정부24 API | 10,000건 | `data/raw/gov24_policies.csv` |
| **합계** | **10,367건** | ChromaDB에 저장됨 |

- 청크 구조: 정책 1개 = 청크 1개 (1:1 매핑, `chunk_id = policy_id + "_01"`)
- 청크 컬럼: `chunk_id`, `policy_id`, `policy_name`, `category`, `region`, `source_url`, `text`
- `text` 안에 지원대상, 지원내용, 신청방법, 신청기한 등 모든 정보 포함
- `age_condition`, `benefit_amount`, `application_method` 등은 최태홍 PostgreSQL에서 관리 (RAG 반환 불필요)

---

## 4. 파이프라인 구조

```
사용자 질문 + user_condition
    ↓
build_search_query()  ← user_condition을 쿼리에 자연어로 보강
    ↓
HybridSearcher.search()  ← BM25(40%) + BGE-M3 Dense(60%), alpha=0.6
    ↓
rerank()  ← bge-reranker-v2-m3로 정밀 재정렬, top_k=5
    ↓
crag_quality_check()  ← 품질 점수 평균으로 3단계 분기
    ↓
generate_answer()  ← gemma3:1b (Ollama), 문서 기반 답변 생성
    ↓
success_response() / error_response()
```

---

## 5. 핵심 모델 결정 사항 (변경 금지)

| 항목 | 결정값 | 근거 |
|------|--------|------|
| 임베딩 모델 | `BAAI/bge-m3` | MTEB 한국어 벤치마크 최상위 |
| 하이브리드 alpha | `0.6` | 실험 결과 0.6 이상 수렴 (0.844), 최적 균형점 |
| Reranker | `BAAI/bge-reranker-v2-m3` | BGE-M3와 동일 계열, 한국어 강함 |
| LLM | `gemma3:1b` (Ollama) | VRAM 8GB 한계로 4b→1b 교체 |
| 벡터 DB | ChromaDB | 벡터 + 메타데이터 통합 관리 |
| HyDE | **제거** | 실험 결과 효과 없음, 30~40초 느림 |
| CRAG | **사용 중** | 품질 낮을 때 재검색/폴백으로 품질 보완 |

> ⚠️ alpha, 모델명, HyDE 제거 결정은 실험 데이터 기반이므로 임의로 변경하지 마세요.

---

## 6. 파일 구조 및 역할

```
rag/
├── CLAUDE.md         # 이 파일 (프로젝트 가이드)
├── pipeline.py       # RAG 메인 파이프라인 (benepick_rag 함수)
├── searcher.py       # 하이브리드 검색기 (BM25 + BGE-M3 Dense)
├── searcher_sparse.py # BGE-M3 Sparse 검색기 (실험용, 미사용)
├── embedder.py       # BGE-M3 임베딩 생성
├── preprocessor.py   # 데이터 전처리 및 청킹
├── collector.py      # 복지로/정부24 API 수집
├── vector_store.py   # ChromaDB 저장/로드
├── evaluate.py       # Ragas 평가 스크립트
├── chroma_db/        # ChromaDB 벡터 DB
└── data/
    ├── raw/          # 원본 CSV
    └── processed/    # 청크 CSV + 임베딩 npy
        └── gov24/    # 정부24 별도 저장
```

---

## 7. 팀 공통 변수명 규칙 (반드시 준수)

| 필드명 | 타입 | 올바른 예시 | 잘못된 예시 | 비고 |
|--------|------|------------|------------|------|
| `policy_id` | string | `"101"` | `101` (숫자X) | DB 참조키는 항상 string |
| `chunk_id` | string | `"101_01"` | `101_01` (따옴표 없이X) | policy_id + 순번 |
| `score` | float | `0.92` | `"92%"` or `92` | 0~1 사이 소수 |
| `eligibility_score` | float | `0.92` | `"높음"` or `92` | 0~1 사이 소수 |
| `rank` | int | `1` | `"1위"` or `1.0` | 1부터 시작하는 정수 |
| `benefit_amount` | int | `2400000` | `"240만원"` | 원 단위 정수 |
| `age` | int | `27` | `"27세"` or `27.0` | 만 나이 정수 |
| `is_applicable` | bool | `true` / `false` | `"가능"` or `1` | 소문자 true/false |
| `timestamp` | string | `"2026-03-20T14:30:00"` | `"2026.03.20"` | ISO 8601 형식 |
| `application_period` | string | `"2026-03-01~2026-12-31"` | `"2026.03.01~"` | ISO 8601 형식 |
| `lang_code` | string | `"ko"` / `"en"` / `"vi"` / `"zh"` | `"한국어"` | ISO 639-1 코드 |
| `search_time_ms` | int | `120` | `"120ms"` | 밀리초 정수 |

```python
# 응답 형식 — 반드시 아래 헬퍼 함수 사용
success_response(data: dict) → {"success": True, "data": ..., "timestamp": ...}
error_response(code, message) → {"success": False, "error_code": ..., ...}
```

---

## 8. API 엔드포인트 스펙

| 메서드 | URL | 기능 | 요청 Body | 담당자 |
|--------|-----|------|-----------|--------|
| POST | `/api/search` | RAG 검색 + 스코어링 | query, user_condition | 박종민·최태홍 |
| GET | `/api/policy/{id}` | 정책 상세 조회 | path param: policy_id | 최태홍 |
| POST | `/api/portfolio` | 포트폴리오 최적화 | results 리스트 | 최태홍·최은철 |
| POST | `/api/apply/checklist` | 신청 체크리스트 생성 | policy_id, user_info | 최은철·남정현 |
| POST | `/api/apply/form` | 신청서 자동 작성 | policy_id, user_info | 최은철 |
| POST | `/api/log` | 사용자 로그 저장 | query_log 객체 | 최태홍 |
| POST | `/api/translate` | 정책 내용 번역 | text, lang_code | 최은철 |

### POST `/api/search` 상세 스펙

**요청 Body:**
```json
{
  "query": "서울 청년 주거지원",
  "user_condition": {
    "age": 27,
    "region": "서울특별시",
    "income_level": "중위소득 52%",
    "household_type": "1인 가구",
    "employment_status": "미취업",
    "housing_type": "월세"
  },
  "lang_code": "ko"
}
```

**응답:**
```json
{
  "success": true,
  "data": {
    "query": "서울 청년 주거지원",
    "answer": "...",
    "lang_code": "ko",
    "user_condition": {...},
    "results": [
      {
        "policy_id": "101",
        "chunk_id": "101_01",
        "policy_name": "청년 월세 한시 특별지원",
        "score": 0.92,
        "rank": 1,
        "category": "주거지원",
        "region": "서울특별시",
        "source_url": "https://bokjiro.go.kr",
        "evidence_text": "서울 거주 만 19~34세..."
      }
    ],
    "total_count": 5,
    "search_time_ms": 1200
  },
  "timestamp": "2026-04-02T10:00:00"
}
```

---

## 9. 에러 코드 목록

| error_code | HTTP | 의미 | 담당자 | 해결 방법 |
|------------|------|------|--------|-----------|
| `SEARCH_FAILED` | 500 | RAG 검색 실패 | 박종민 | 벡터 DB 연결 확인 |
| `INVALID_CONDITION` | 400 | 사용자 조건 형식 오류 | 최태홍 | Pydantic 검증 확인 |
| `POLICY_NOT_FOUND` | 404 | 정책 ID 없음 | 최태홍 | policy_id 확인 |
| `SCORING_FAILED` | 500 | 스코어링 계산 실패 | 최은철 | sLLM 서버 확인 |
| `TRANSLATE_FAILED` | 500 | 번역 모델 오류 | 최은철 | mBART 서버 확인 |
| `API_LIMIT_EXCEEDED` | 429 | 공공 API 호출 횟수 초과 | 고준 | time.sleep() 추가 |
| `DB_CONNECTION_ERROR` | 503 | DB 연결 실패 | 최태홍 | PostgreSQL 상태 확인 |
| `AUTH_FAILED` | 401 | API 키 인증 실패 | 최태홍 | API 키 재확인 |

---

## 10. 환경변수 (.env) 목록

```env
# 공공 API 키
GOV24_API_KEY=       # 정부24 API (data.go.kr 발급, 담당: 고준)
BOKJIRO_API_KEY=     # 복지로 API (data.go.kr 발급, 담당: 고준)
YOUTH_API_KEY=       # 온통청년 API (담당: 고준)

# 데이터베이스
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=benepick
POSTGRES_USER=benepick_user
POSTGRES_PASSWORD=   # 노출 금지

# 벡터 DB
CHROMA_HOST=localhost        # 개발용
PINECONE_API_KEY=            # 운영용
PINECONE_ENV=us-east1-gcp

# 서버 설정
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
FRONTEND_URL=http://localhost:3000   # CORS 설정용

# sLLM 설정
OLLAMA_BASE_URL=http://localhost:11434
MODEL_NAME=gemma3:1b
TRANSLATION_MODEL=mbart-finetuned
```

---

## 11. Git 브랜치 전략

| 브랜치명 | 용도 | Push 권한 |
|----------|------|-----------|
| `main` | 최종 배포용 | 팀장(박종민) 승인 후만 |
| `develop` | 통합 테스트용 | PR 통해서만 |
| `feature/rag-search` | RAG 검색 개발 | 박종민 |
| `feature/backend-api` | 백엔드 API 개발 | 최태홍 |
| `feature/data-pipeline` | 데이터 수집 | 고준 |
| `feature/frontend-ui` | 프론트엔드 UI | 남정현 |
| `feature/prompt-scoring` | 프롬프트 & 스코어링 | 최은철 |

**커밋 메시지 규칙:**

| prefix | 의미 | 예시 |
|--------|------|------|
| `feat` | 새 기능 추가 | `feat: RAG 하이브리드 검색 구현` |
| `fix` | 버그 수정 | `fix: 스코어링 점수 계산 오류 수정` |
| `refactor` | 코드 리팩토링 | `refactor: 청킹 로직 개선` |
| `docs` | 문서 수정 | `docs: API 명세 업데이트` |
| `test` | 테스트 코드 | `test: RAG 검색 유닛 테스트 추가` |
| `chore` | 빌드/설정 변경 | `chore: Docker 설정 수정` |
| `style` | 코드 포맷 변경 | `style: 들여쓰기 통일` |

---

## 12. 환경 설정

```
GPU: RTX 4060 Laptop (VRAM 8GB)
Python: 3.12
venv 경로: C:\Users\dlfns\OneDrive\바탕 화면\benepick\venv
프로젝트 경로: C:\Users\dlfns\OneDrive\바탕 화면\benepick\rag
PyTorch: 2.5.1+cu121 (CUDA 12.1)
Ollama: gemma3:1b (로컬 실행)
```

**venv 활성화:**
```powershell
& "C:\Users\dlfns\OneDrive\바탕 화면\benepick\venv\Scripts\activate.ps1"
```

**⚠️ VRAM 주의사항:**
- BGE-M3 + gemma3:1b 동시 로드 시 VRAM 거의 풀로 사용 (7.9GB/8GB)
- Ragas 평가 시 임베딩은 반드시 `device="cpu"` 로 설정
- OOM 발생 시 Ollama 트레이에서 완전 종료 후 재시작

---

## 13. Ragas 평가 현황

**평가 결과 (2026-04-02 기준, gemma3:1b):**

| 지표 | 점수 | 의미 |
|------|------|------|
| faithfulness | 0.9769 | 환각 거의 없음 ✅ |
| answer_relevancy | 0.5582 | 개선 여지 있음 |
| 평균 | 0.7675 | 전체적으로 양호 |

**Ragas 주의사항 (ragas 0.4.x):**
- `context_precision` → `reference` 컬럼 필요 (ground_truth 없으면 사용 불가)
- `ContextRelevance` → OpenAI 전용, Ollama 미지원
- `LangchainLLMWrapper` deprecated → 현재는 그대로 사용 (동작은 함)
- 점수가 list로 반환될 수 있음 → `safe_score()` 헬퍼로 처리

---

## 14. CRAG 로직

```python
QUALITY_HIGH   = 0.7  # 이상: 원본 결과 사용
QUALITY_MEDIUM = 0.4  # 이상: 조건 완화 재검색 (지역/가구 제거)
                       # 미만: 카테고리 폴백 검색
```

**폴백 카테고리 맵:**
```python
'월세/전세' → '청년 주거 지원'
'취업/실업' → '청년 고용 지원'
'생계'      → '저소득 생활 지원'
'의료'      → '의료비 지원'
'출산/육아' → '출산 육아 지원'
'노인'      → '노인 복지 지원'
'장애'      → '장애인 복지 지원'
```

---

## 15. 다음 할 일 (우선순위 순)

1. **FastAPI 연결** — 최태홍과 `POST /api/search` 엔드포인트 연결
2. **스트리밍 응답 구현** — LLM 답변 스트리밍
3. **고용24 API 추가** — 데이터 소스 확장
4. **임베딩 모델 교체 실험** — GPU 서버에서 진행 (로컬 VRAM 부족)
   - 후보: `intfloat/multilingual-e5-large`, `jhgan/ko-sroberta-multitask`
5. **BM25 vs BGE-M3 Sparse 비교** — `searcher_sparse.py` 활용

---

## 16. 코드 작성 규칙

1. **응답 형식**: 반드시 `success_response()` / `error_response()` 사용
2. **변수명**: 팀 공통 규칙 준수 (7번 섹션 참고)
3. **score**: 항상 `float`, `0~1` 사이, `round(..., 4)`
4. **lang_code**: ISO 639-1 ("ko", "en", "vi", "zh")
5. **에러 처리**: 모든 함수에 try/except 필수
6. **주석**: 한국어로 작성
7. **HyDE**: 절대 다시 추가하지 말 것 (실험으로 제거 결정됨)
8. **alpha**: 0.6 고정, 임의 변경 금지
