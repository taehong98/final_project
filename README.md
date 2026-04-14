# BenePick

BenePick은 FastAPI 백엔드, Next.js 프론트엔드, Python RAG 파이프라인으로 구성된 복지 정책 추천 서비스입니다.

현재 실행 구조는 다음과 같습니다.

```text
프론트엔드 -> 백엔드 FastAPI -> app.services.rag.search_rag() -> rag.pipeline.benepick_rag()
```

RAG는 별도 서버로 실행하지 않고 백엔드 내부 함수로 호출합니다. 따라서 `uvicorn api:app --port 8001`을 따로 실행할 필요가 없습니다.

## 주요 구조

```text
app/          FastAPI 백엔드
rag/          RAG 검색 및 답변 생성 파이프라인
frontend/     Next.js 프론트엔드
processed/    RAG 검색용 전처리 데이터
raw/          원본 정책 데이터
chroma.sqlite3, UUID 폴더들
              Chroma 벡터DB 데이터
```

## 준비

프로젝트 루트는 다음 경로입니다.

```powershell
cd C:\Users\heuks\Desktop\final_rag\final_project
```

Python 패키지는 하나의 파일에서 설치합니다.

```powershell
pip install -r requirements.txt
```

프론트엔드 패키지는 `frontend` 폴더에서 설치합니다.

```powershell
cd C:\Users\heuks\Desktop\final_rag\final_project\frontend
npm install
```

`.env.example`을 참고해서 `.env`를 준비합니다. 실제 API 키와 DB 비밀번호는 `.env`에만 넣고 Git에는 올리지 않습니다.

## 실행

백엔드는 프로젝트 루트에서 실행합니다.

```powershell
cd C:\Users\heuks\Desktop\final_rag\final_project
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

프론트엔드는 별도 PowerShell 창에서 실행합니다.

```powershell
cd C:\Users\heuks\Desktop\final_rag\final_project\frontend
npm run dev
```

브라우저에서 접속합니다.

```text
http://localhost:3000
```

프론트엔드는 기본적으로 `http://127.0.0.1:8000/api/v1` 백엔드 API를 호출합니다. 다른 주소를 쓰려면 `frontend/.env.local`에 아래처럼 설정합니다.

```text
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api/v1
```

## 참고

RAG가 백엔드 내부에서 실행되므로 첫 검색 요청에서는 임베딩 모델, reranker, Ollama 모델 로딩 때문에 시간이 걸릴 수 있습니다. Ollama를 사용하는 경우 로컬에서 `gemma3:1b` 모델을 사용할 수 있어야 합니다.
