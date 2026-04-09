# 베네픽 최종 프로젝트

복지로 + 정부24 정책 데이터를 바탕으로 사용자 조건에 맞는 복지 정책을 추천하는 프로젝트입니다.

## 현재 구조
- 자연어 검색 추천: **ChromaDB + BM25 하이브리드 검색**
- 일부 보조 조회: **sqlite(`gov_benefits.db`)**
- 수급 가능성 판정: `scoring.py`
- 카드/대시보드 변환: `analysis.py`
- API 서버: `main.py`

즉, 현재는 **완전 Chroma 단일화가 아니라 하이브리드 구조**입니다.

## 실행 전 준비
프로젝트 루트에 아래가 있어야 합니다.
- `chroma_db/`
- `data/processed/chunks.csv`
- `data/processed/gov24/chunks.csv` (있으면 함께 사용)
- `.env` (`OPENAI_API_KEY` 필요 시)

## 설치
```bash
pip install -r requirements.txt
```

## 서버 실행
```bash
uvicorn main:app --reload --port 8000
```

## 주요 파일
- `policy_search.py`: Chroma + BM25 하이브리드 검색
- `scoring.py`: 지역/가구/나이/소득 기준 기반 1차 판정
- `analysis.py`: 카드 데이터, 예상 수혜액, 대시보드용 JSON 생성
- `main.py`: FastAPI 엔드포인트

## 이번 수정 포인트
### 1) 지역 오판정 보강
- 중앙부처 전국 정책이 본문 안의 지역명 때문에 특정 지역 정책으로 오인되지 않도록 수정
- `긴급복지 생계지원` 같은 케이스에서 `보건복지부` + 지역 제한 문구 없음이면 전국으로 처리

### 2) 예상 수혜액 계산 추가
- `월 20만원 × 최대 12개월`
- `최대 300만원`
- `연 70만원`
같은 금액을 대시보드 총액으로 합산

### 3) 제출용 보수형 스코어 유지
- 신혼부부 / 한부모 / 미혼모부 / 다자녀 / 임산부 전용 정책은 하드 필터
- 긴급복지류는 위기상황 확인 soft-fail 유지

## 확인 방법
### Chroma 적재 확인
- `data/processed` 청크 개수와 `chroma_db` 내 임베딩 개수가 같은지 확인
- 대표 질의 5개 회귀 테스트
  - 청년 월세
  - 청년수당
  - 전세보증금 반환보증
  - 저소득 생계
  - 장애인 고용

### API 테스트
`POST /analyze` 요청 후 다음 항목 확인
- `dashboard_stats.expected_total_benefit_label`
- `cards[].benefit_label`
- 서울 사용자 입력 시 서울/전국 정책이 상위에 오는지
- 전국 정책이 본문 지역명 때문에 0점 처리되지 않는지
