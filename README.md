# Hansung_AX
2026 한성대학교 AX 프론티어 공모전

# 한성대학교 규정 마스터 AI

한성대학교 규정관리시스템의 규정과 첨부파일(HWP)을 크롤링하여 벡터 DB에 저장하고,
사용자 질문에 대해 규정 근거를 명시하며 답변하는 AI 웹 서비스.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| 크롤링 | Python + requests + BeautifulSoup + pyhwp |
| 벡터 임베딩 | sentence-transformers (로컬, 무료) |
| 벡터 DB | PostgreSQL + pgvector (Docker 컨테이너) |
| AI 답변 생성 | Groq API (Llama 4 Scout 17B, 무료) |
| 백엔드 | FastAPI (Python) |
| 프론트엔드 | HTML / CSS / JS |

---

## 사전 설치

### 1. Python 패키지
```powershell
pip install requests beautifulsoup4 fastapi uvicorn psycopg2-binary python-dotenv sentence-transformers groq python-docx reportlab pdfminer.six pdfplumber pyhwp lxml PyJWT python-multipart
```

### 2. Docker Desktop
- https://www.docker.com/products/docker-desktop 에서 설치
- 설치 후 Docker Desktop 실행 (백그라운드 유지)

### 3. PostgreSQL + pgvector 컨테이너 실행 (한 번만)
```powershell
docker run -d --name hansung-db `
  -e POSTGRES_PASSWORD=비밀번호 `
  -e POSTGRES_DB=hansungrules `
  -p 5432:5432 `
  pgvector/pgvector:pg16
```

---

## 파일 구조

```
Hansung_AX/
├── .env                  # API 키, DB 연결 정보, 관리자 계정 (git 업로드 금지)
├── .gitignore
├── crawler.py            # 한성대 규정 크롤러 (HWP 첨부파일 추출 포함)
├── patch_codes.py        # 규정 코드 패치 스크립트 (최초 1회)
├── build_db.py           # 벡터 DB 구축 스크립트
├── server.py             # FastAPI 백엔드 서버
├── index.html            # 메인 프론트엔드
├── login.html            # 관리자 로그인 페이지
├── upload.html           # 규정 파일 업로드 페이지 (로그인 필요)
├── HSU_logo.png          # 한성대 로고
├── hansung_rules.json    # 크롤링 결과 (HWP 본문 포함)
├── requirements.txt      # 패키지 목록
├── uploads/              # 업로드된 규정 파일 로컬 백업
├── routers/
│   ├── __init__.py
│   └── teacher.py        # 교직원 전용 기능 (충돌 분석, PDF/Word 내보내기)
└── README.md
```

---

## 각 파일 역할

### crawler.py
- rule.hansung.ac.kr 규정관리시스템 크롤링
- lawDetail.do → lawFullView.do → lawFullContent.do 3단계로 조항 본문 수집
- `javascript:fileDown(SEQ, 'ori')` 패턴 감지 → POST `/lmxsrv/fileDown.do` 로 첨부파일 다운로드
- HWP(pyhwp CLI), HWPX(ZIP+XML), PDF(pdfplumber), DOCX(python-docx) 텍스트 추출
- 첨부파일 텍스트를 본문에 합산하여 hansung_rules.json 저장
- SEQ 1~1000 순회, 중간저장 지원 → 재실행 시 이어서 진행
- 쿠키 만료 시 브라우저에서 갱신 필요

### patch_codes.py
- hansung_rules.json에 규정 코드(1-0-1 등) 추가
- 규정 목록의 편별 분류(제1편~제8편)를 위해 필요
- 크롤링 후 최초 1회만 실행

### build_db.py
- hansung_rules.json 읽어서 조항(제N조) 단위로 청크 분할
- sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` 로컬 임베딩 (384차원)
- Docker PostgreSQL의 rule_chunks 테이블에 저장

### server.py (FastAPI)

**정적 파일 서빙**
- `GET /` → index.html
- `GET /login-page` → login.html
- `GET /upload` → upload.html
- `GET /HSU_logo.png` → 로고 이미지
- `GET /health` → DB 연결 상태 확인

**규정 검색**
- `GET /rules` → 전체 규정 목록 (편별 분류 + 업로드 규정 통합)
- `POST /query` → 벡터 + 키워드 하이브리드 검색 → Groq 답변 생성 (멀티턴 대화 지원)
- `POST /search-rules` → 규정 목록 키워드 검색 (본문 + 첨부파일 내용 포함)

**관리자 인증 (DB 없이 .env 기반)**
- `POST /login` → 아이디/비밀번호 검증 → JWT 토큰 발급 (12시간 유효)

**규정 업데이트 (JWT 인증 필요)**
- `POST /upload-regulation` → 파일 업로드 → 텍스트 추출 → 임베딩 → DB 저장 (중복 체크, 편 자동 분류)
- `GET /uploaded-rules` → 업로드된 규정 목록 조회
- `DELETE /uploaded-rules/{filename}` → 업로드된 규정 DB에서 삭제

**교직원 도구**
- `POST /conflict/` → 문서 업로드 → 기존 규정과 충돌 분석
- `POST /export/pdf` → 답변 PDF 다운로드 (한글 폰트 자동 감지)
- `POST /export/docx` → 답변 Word 다운로드 (맑은 고딕 적용)

### login.html
- 관리자 로그인 페이지 (`/login-page`)
- 서버 `/login` API 호출 → JWT 토큰 localStorage 저장 → `/upload` 이동
- 이미 로그인된 경우(유효 토큰) 바로 업로드 페이지 리다이렉트

### upload.html
- 규정 파일 업로드 페이지 (`/upload`)
- JWT 없거나 만료 시 자동으로 로그인 페이지 이동
- 여러 파일 동시 선택 또는 드래그 앤 드롭
- 파일별 실시간 상태 표시 + 전체 진행바
- 업로드된 규정 목록 + 삭제 버튼 (DB에서 즉시 제거)

### index.html
- 교직원/학생 모드 전환
  - 교직원 모드: 복무, 급여, 임용, 징계 예시 질문 / 🔄 규정 업데이트 버튼 표시
  - 학생 모드: 학사, 장학, 졸업, 수강 예시 질문 / 규정 업데이트 버튼 숨김
- 왼쪽 사이드바: 대화 내역 저장 및 복원 (localStorage, 최대 30개)
  - 항목 클릭 시 즉시 복원 (소스·관련질문 포함, 애니메이션 없음)
  - 구버전 히스토리는 백그라운드 재조회 후 자동 업데이트
  - 개별 삭제(hover 시 ✕) / 전체 삭제
- 답변 카드: 타이핑 애니메이션 + 근거 조항 + 유사도 + 담당부서 + 관련질문 4개 버튼
- 답변 PDF/Word 저장 버튼
- 규정 목록 탭:
  - 검색창 하나로 통합 (규정명 + 본문 + 첨부파일 내용 동시 검색)
  - 검색어 없을 때 → 편별 분류 목록 전체 표시
  - 검색어 입력 시 → 키워드 포함된 규정만 표시 (검색어 빨간색 하이라이트)
  - 결과 카드 기본 열림 상태, 클릭으로 접기/펼치기
- 📋 교직원 도구 탭 (교직원 모드에서만 표시): 문서 업로드 + 충돌 분석

### routers/teacher.py
- 교직원 전용 기능
- PDF·DOCX·TXT·JSON 파일 업로드 → 기존 규정 DB와 비교 → 충돌 리포트 (높음/보통/낮음)
- 답변 내용을 PDF 또는 DOCX 파일로 내보내기
  - PDF: Windows malgun.ttf / Linux NanumGothic 자동 감지
  - DOCX: 맑은 고딕 폰트 강제 적용

---

## .env 설정

```
GROQ_API_KEY=여기에_Groq_키
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules

# 관리자 계정 (미설정 시 기본값: admin / 1234)
ADMIN_ID=admin
ADMIN_PW=1234

# JWT 서명 키 (32자 이상 권장)
SECRET_KEY=여기에_랜덤_문자열_32자_이상
```

- Groq API 키: https://console.groq.com → API Keys → Create (무료)

---

## 실행 순서

### Step 1. .env 파일 생성
```
GROQ_API_KEY=...
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules
ADMIN_ID=admin
ADMIN_PW=1234
SECRET_KEY=랜덤32자이상문자열
```

### Step 2. 크롤링
```powershell
python crawler.py
```
- 약 30~50분 소요 (HWP 첨부파일 다운로드 포함)
- 쿠키 만료 시 아래 쿠키 갱신 방법 참고

### Step 2-1. 규정 코드 패치 (최초 1회)
```powershell
python patch_codes.py
```

### Step 3. 벡터 DB 구축
```powershell
python build_db.py
```
- 첫 실행 시 임베딩 모델 자동 다운로드 (약 500MB, 1회만)
- Docker 컨테이너 실행 중이어야 함
- 완료 후 약 11,000개 청크 생성

### Step 4. 서버 실행
```powershell
uvicorn server:app --reload --port 8000
```

### Step 5. 웹 접속
```
http://127.0.0.1:8000
```

---

## 주요 기능 요약

| 기능 | 설명 |
|------|------|
| AI 규정 검색 | 벡터 + 키워드 하이브리드 검색, 멀티턴 대화 지원 |
| HWP 첨부파일 | 규정 첨부파일 텍스트 자동 추출 및 DB 반영 (약 11,000청크) |
| 규정 목록 검색 | 규정명·본문·첨부파일 내용 통합 키워드 검색 + 하이라이트 |
| 답변 형식 | 제목 + 본문 + 출처 + 담당부서 + 관련질문 4개 버튼 |
| 대화 내역 | localStorage 영구 저장, 클릭 시 즉시 복원 (소스 포함) |
| 규정 업데이트 | 파일 업로드 → Groq 자동 편 분류 → DB 즉시 반영 |
| 내보내기 | PDF / DOCX (한글 폰트 자동 처리) |
| 충돌 분석 | 문서 업로드 → 기존 규정 비교 → 심각도별 리포트 |
| 모드 전환 | 교직원 / 학생 모드 (버튼 노출 조건, 예시 질문 상이) |

---

## 규정 업데이트 방법

1. http://127.0.0.1:8000 접속 → **교직원 모드** 선택
2. nav에서 **🔄 규정 업데이트** 클릭 (📋 교직원 도구 바로 옆)
3. 관리자 로그인 (`admin` / `1234`, `.env`에서 변경 가능)
4. 파일 업로드 (PDF·DOCX·TXT·JSON, 여러 파일 동시 가능)
5. 업로드 즉시 Groq가 1~8편 자동 분류 → DB 등록 → 검색 반영

**업로드된 규정 삭제:** 업로드 페이지 하단 목록 → 삭제 버튼

---

## 쿠키 갱신 방법 (크롤링 세션 만료 시)

1. Chrome에서 rule.hansung.ac.kr 접속 후 아무 규정 클릭
2. F12 → Network 탭 → F5 새로고침
3. `lawDetail.do` 요청 클릭 → Request Headers → Cookie 값 전체 복사
4. `crawler.py`의 `COOKIES` 딕셔너리 교체 후 재실행

---

## 코드 공유 시 주의사항

- `.env` 파일은 절대 깃허브에 올리지 말 것
- 각자 Groq API 키 발급 필요 (무료, https://console.groq.com)
- 각자 Docker Desktop 설치 및 컨테이너 실행 필요
- 첫 실행 시 임베딩 모델 자동 다운로드 (인터넷 연결 필요)
- `users.db` 파일 불필요 — 관리자 계정은 `.env`로 관리

---

## DB 연결 정보 (Docker)

| 항목 | 값 |
|------|-----|
| Host | localhost |
| Port | 5432 |
| DB명 | hansungrules |
| User | postgres |
| 테이블 | rule_chunks |
| 벡터 차원 | 384 (paraphrase-multilingual-MiniLM-L12-v2) |
| 총 청크 수 | 약 11,266개 (HWP 첨부파일 포함) |

### rule_chunks 테이블 구조

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | TEXT | 고유 식별자 (기존: 숫자, 업로드: 타임스탬프) |
| rule_title | TEXT | 규정명 |
| article | TEXT | 조항명 (업로드 규정은 제N조 자동 파싱) |
| department | TEXT | 담당부서 (업로드 규정: "업로드:N" 편 분류 태그) |
| url | TEXT | 원문 링크 (업로드 규정: `upload://파일명`) |
| content | TEXT | 조항 내용 (HWP 첨부파일 텍스트 포함) |
| embedding | VECTOR(384) | 임베딩 벡터 |