# Hansung_AX
2026 한성대학교 AX 프론티어 공모전

# 한성대학교 규정 마스터 AI

한성대학교 규정관리시스템의 규정을 크롤링하여 벡터 DB에 저장하고,
사용자 질문에 대해 규정 근거를 명시하며 답변하는 AI 웹 서비스.

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| 크롤링 | Python + requests + BeautifulSoup |
| 벡터 임베딩 | sentence-transformers (로컬, 무료) |
| 벡터 DB | PostgreSQL + pgvector (Docker 컨테이너) |
| AI 답변 생성 | Groq API (Llama 4 Scout 17B, 무료) |
| 백엔드 | FastAPI (Python) |
| 프론트엔드 | HTML / CSS / JS |

---

## 사전 설치

### 1. Python 패키지
```powershell
pip install requests beautifulsoup4 fastapi uvicorn psycopg2-binary python-dotenv sentence-transformers groq python-docx reportlab pdfminer.six python-multipart PyJWT
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
├── crawler.py            # 한성대 규정 크롤러
├── patch_codes.py        # 규정 코드 패치 스크립트 (최초 1회)
├── build_db.py           # 벡터 DB 구축 스크립트
├── server.py             # FastAPI 백엔드 서버
├── index.html            # 메인 프론트엔드
├── login.html            # 관리자 로그인 페이지
├── upload.html           # 규정 파일 업로드 페이지 (로그인 필요)
├── HSU_logo.png          # 한성대 로고
├── hansung_rules.json    # 크롤링 결과
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
- lawDetail.do → lawFullView.do → lawFullContent.do 3단계로 실제 조항 본문 수집
- 세션 쿠키 기반 인증 (주기적으로 갱신 필요)
- SEQ 1~1000 순회, 중간저장 지원 → 재실행 시 이어서 진행
- 결과를 hansung_rules.json으로 저장

### patch_codes.py
- hansung_rules.json에 규정 코드(1-0-1 등) 추가
- 규정 목록의 편별 분류(제1편~제8편)를 위해 필요
- 크롤링 후 최초 1회만 실행

### build_db.py
- hansung_rules.json 읽어서 조항(제N조) 단위로 청크 분할
- sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` 로컬 임베딩 (384차원)
- Docker PostgreSQL의 rule_chunks 테이블에 저장
- 약 5분 내 완료

### server.py (FastAPI)

**정적 파일 서빙**
- `GET /` → index.html
- `GET /login-page` → login.html
- `GET /upload` → upload.html
- `GET /HSU_logo.png` → 로고 이미지
- `GET /health` → DB 연결 상태 확인

**규정 검색**
- `GET /rules` → 전체 규정 목록 (편별 분류, hansung_rules.json 기반)
- `POST /query` → 벡터 + 키워드 하이브리드 검색 → Groq 답변 생성

**관리자 인증 (DB 없이 .env 기반)**
- `POST /login` → 아이디/비밀번호 검증 → JWT 토큰 발급 (12시간 유효)

**규정 업데이트 (JWT 인증 필요)**
- `POST /upload-regulation` → 파일 업로드 → 텍스트 추출 → 임베딩 → DB 저장
- `GET /uploaded-rules` → 업로드된 규정 목록 조회
- `DELETE /uploaded-rules/{filename}` → 업로드된 규정 DB에서 삭제

**교직원 도구**
- `POST /conflict/` → 문서 업로드 → 기존 규정과 충돌 분석 (교직원 모드)
- `POST /export/pdf` → 답변 PDF 다운로드
- `POST /export/docx` → 답변 Word 다운로드

### login.html
- 관리자 로그인 페이지 (`/login-page`)
- 서버 `/login` API 호출 → JWT 토큰 발급
- 로그인 성공 시 `localStorage`에 토큰 저장 → `/upload` 자동 이동
- 이미 로그인된 경우 바로 업로드 페이지로 리다이렉트

### upload.html
- 규정 파일 업로드 페이지 (`/upload`)
- JWT 토큰 없거나 만료 시 자동으로 로그인 페이지로 이동
- **다중 파일 업로드**: 여러 파일 동시 선택 또는 드래그 앤 드롭
- 파일별 실시간 상태 표시 (대기 → 업로드 중 → 완료/실패)
- 전체 진행바 표시
- 업로드된 규정 목록 + 삭제 버튼 (DB에서 즉시 제거)

### index.html
- 교직원/학생 모드 전환
  - 교직원 모드: 복무, 급여, 임용, 징계 관련 예시 질문 제공
  - 학생 모드: 학사, 장학, 졸업, 수강 관련 예시 질문 제공
- 왼쪽 사이드바: 대화 내역 저장 및 복원
- 답변 카드: 타이핑 애니메이션 + 근거 조항 + 유사도 + 담당부서 + 추가질문 4개
- 답변 PDF/Word 저장 버튼
- 규정 목록 브라우저 (편별 분류 + 검색)
- 📋 교직원 도구 탭 (교직원 모드에서만 표시): 문서 업로드 + 충돌 분석
- 🔄 규정 업데이트 버튼 (교직원 모드에서만 표시): 관리자 로그인 → 규정 업로드

### routers/teacher.py
- 교직원 전용 기능
- PDF·DOCX·TXT 파일 업로드 → 기존 규정 DB와 비교 → 충돌 리포트 (높음/보통/낮음)
- 답변 내용을 PDF 또는 DOCX 파일로 내보내기

---

## .env 설정

```
GROQ_API_KEY=여기에_Groq_키
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules

# 관리자 계정 (미설정 시 기본값: admin / 1234)
ADMIN_ID=admin
ADMIN_PW=1234

# JWT 서명 키 (미설정 시 기본값 사용, 실서비스 시 반드시 변경)
SECRET_KEY=여기에_랜덤_문자열_32자_이상
```

- Groq API 키: https://console.groq.com → API Keys → Create (무료, 신용카드 불필요)
- 비밀번호는 Docker 컨테이너 실행 시 설정한 값과 동일하게

---

## 실행 순서

### Step 1. .env 파일 생성
위 `.env 설정` 참고하여 프로젝트 폴더에 `.env` 파일 생성

### Step 2. 크롤링 (hansung_rules.json이 이미 있으면 생략 가능)
```powershell
python crawler.py
```
- 약 20~30분 소요
- 쿠키 만료 시 브라우저에서 새 쿠키 복사 후 crawler.py의 COOKIES 값 교체

### Step 2-1. 규정 코드 패치 (크롤링 후 최초 1회)
```powershell
python patch_codes.py
```
- 규정 목록의 편별 분류(제1편~제8편)를 위한 코드 정보 추가

### Step 3. 벡터 DB 구축 (한 번만 실행)
```powershell
python build_db.py
```
- 첫 실행 시 임베딩 모델 자동 다운로드 (약 500MB, 1회만)
- 이후 약 5분 내 완료
- Docker 컨테이너가 실행 중이어야 함

### Step 4. 서버 실행
```powershell
uvicorn server:app --reload --port 8000
```

### Step 5. 웹 접속
브라우저에서 http://127.0.0.1:8000

---

## 규정 업데이트 방법

운영 중에 새 규정을 추가하거나 기존 규정을 보완하려면:

1. http://127.0.0.1:8000 접속 → 교직원 모드 선택
2. 상단 **🔄 규정 업데이트** 버튼 클릭
3. 관리자 로그인 (기본 `admin` / `1234`, `.env`에서 변경 가능)
4. 규정 파일 업로드 (PDF·DOCX·TXT·JSON, 여러 파일 동시 가능)
5. 업로드 즉시 검색 DB에 반영됨

**업로드된 규정 삭제:**
- 업로드 페이지 하단 목록에서 삭제 버튼 클릭 → DB에서 즉시 제거

**지원 형식:**

| 형식 | 비고 |
|------|------|
| TXT | UTF-8 / CP949 / EUC-KR 자동 감지 |
| JSON | `[{"title":..., "content":...}]` 또는 임의 구조 |
| DOCX | 텍스트 기반 Word 문서 |
| PDF | 텍스트 기반 PDF (스캔본 불가) |

---

## 쿠키 갱신 방법 (크롤링 세션 만료 시)

1. Chrome에서 rule.hansung.ac.kr 접속 후 아무 규정 클릭
2. F12 → Network 탭 → F5 새로고침
3. lawDetail.do 요청 클릭 → Headers → Cookie 값 전체 복사
4. crawler.py의 COOKIES 딕셔너리 교체 후 재실행

---

## 코드 공유 시 주의사항

- `.env` 파일은 절대 깃허브에 올리지 말 것 (`.gitignore`에 추가되어 있음)
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

### rule_chunks 테이블 구조

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | TEXT | 고유 식별자 (기존 규정: 숫자, 업로드 규정: 타임스탬프) |
| rule_title | TEXT | 규정명 |
| article | TEXT | 조항명 |
| department | TEXT | 담당부서 |
| url | TEXT | 원문 링크 (업로드 규정은 `upload://파일명`) |
| content | TEXT | 조항 내용 |
| embedding | VECTOR(384) | 임베딩 벡터 |