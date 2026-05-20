# Hansung_AX

> **2026 한성대학교 AX 프론티어 공모전 출품작**

# 한성대학교 규정 마스터 AI

한성대학교 규정관리시스템(rule.hansung.ac.kr)의 **규정 315편 / 1,600여 버전**을 첨부파일(HWP/HWPX)까지 모두 크롤링하여 벡터 DB에 적재하고,
학생·교직원의 자연어 질문에 **근거 조항을 명시하며** 답변하는 AI 웹 서비스.
관리자는 한 화면에서 **규정 추가 / 조 단위 개정 / 단어 일괄 치환 / 외부 문서 충돌 분석**까지 모두 처리할 수 있다.

> **무엇이 가능한가**
> - 학생: "휴학 최대 몇 년이에요?" → 학칙 제N조 인용 + 담당부서 직통번호까지 한 화면에
> - 교직원: 새 규정 초안을 업로드 → 기존 315편 중 어느 조항과 부딪치는지 자동 검토
> - 관리자: "○○ 규정 제12조"만 골라 개정 → 자동 백업 → 마음에 안 들면 한 번에 되돌리기
> - 모두: "최근 학사운영규정 뭐가 바뀌었나요?" → 글자 단위 diff 모달로 변경 부분만 빨강·초록 표시

---

## 기술 스택

| 역할 | 기술 |
|------|------|
| 크롤링 | Python + requests + BeautifulSoup + pyhwp + pdfplumber |
| 벡터 임베딩 | sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` (로컬, 384차원, 무료) |
| 벡터 DB | PostgreSQL + pgvector (Docker 컨테이너) |
| AI 답변·분석 | Groq API — Llama 4 Scout 17B (무료) |
| 백엔드 | FastAPI (Python) + JWT 인증 |
| 프론트엔드 | HTML / CSS / Vanilla JS (프레임워크 X) |
| 문서 변환 | python-docx, reportlab, pdfminer.six, pdfplumber, pyhwp |

---

## 핵심 기능 한눈에

| 기능 | 누구 | 설명 |
|---|---|---|
| **AI 규정 챗봇** | 학생·교직원 | 벡터+키워드 하이브리드 검색 → 근거 조항·담당부서·연관질문 4개 자동 표시 |
| **버전 비교 (diff)** | 모두 | "○○ 규정 뭐가 바뀌었나요?" → 조 단위 글자 diff 모달 |
| **규정 추가** | 관리자 | PDF·DOCX·HWP·HWPX 업로드 → AI가 1~8편 자동 분류 → 즉시 DB 반영 |
| **규정 개정 (전체)** | 관리자 | 기존 규정 내용 통째로 교체 + `revisions[]`에 날짜 기록 |
| **규정 개정 (조 단위)** | 관리자 | 조 1개만 교체. 머리글 끝에 `(개정 YYYY-MM-DD)` 자동 부착 |
| **AI 개정안 추출** | 관리자 | 회의안건 PDF 업로드 → AI가 해당 조의 개정(안) 본문만 자동 추출 |
| **AI 형식 검사** | 관리자 | 한성대 규정 표준 형식(조/항/호/목 기호, 띄어쓰기 등) 위반 자동 하이라이트 |
| **단어 일괄 치환** | 관리자 | "총무과 → 총무인사팀" 같은 부서명 변경을 모든 규정에서 한 번에. 미리보기 + 선택 적용 |
| **충돌 분석** | 관리자 | 새 규정 초안 업로드 → 가장 유사한 기존 규정과 조항별 비교 → 심각도별 충돌 항목 + 권고사항 |
| **되돌리기** | 관리자 | 모든 개정 작업은 자동 백업. 백업 목록에서 한 번 클릭으로 개정 전 상태 복원 |
| **PDF/Word 내보내기** | 모두 | 챗봇 답변을 한글 폰트로 깔끔하게 다운로드 |

---

## 데이터 흐름

```
[크롤링]    rule.hansung.ac.kr
                │
                ▼
hansung_rules_history.json    ←  버전 1,600여 개 (versions 배열, is_latest 플래그)
   │
   ├──→ make_rules_json.py ──→ hansung_rules.json    (최신판 315편, 목록 페이지용)
   │
   └──→ build_db.py        ──→ PostgreSQL rule_chunks (11,000여 청크, vector(384))
                                      │
                                      ▼
                            챗봇 /query  ·  /search-rules
```

- **챗봇 검색**: DB의 임베딩 검색 (history 기반으로 빌드됨)
- **규정 목록**: `hansung_rules.json` 직접 읽음
- **개정 작업**: `hansung_rules_history.json`의 최신 버전 content 덮어쓰기 → DB 재색인

---

## 사전 설치

### 1. Python 패키지

```powershell
pip install requests beautifulsoup4 fastapi uvicorn python-multipart `
            psycopg2-binary python-dotenv sentence-transformers groq `
            python-docx reportlab pdfminer.six pdfplumber pyhwp lxml PyJWT
```

### 2. Docker Desktop
- https://www.docker.com/products/docker-desktop 에서 설치
- 설치 후 백그라운드 실행 유지

### 3. PostgreSQL + pgvector 컨테이너 (최초 1회)

```powershell
docker run -d --name hansung-db `
  -e POSTGRES_PASSWORD=비밀번호 `
  -e POSTGRES_DB=hansungrules `
  -p 5432:5432 `
  pgvector/pgvector:pg16
```

이후 PC 껐다 켜도 `docker start hansung-db` 한 줄이면 됨.

---

## 파일 구조

```
Hansung_AX/
├── .env                          # API 키 / DB 연결 / 관리자 계정 (git 업로드 금지)
├── .gitignore
├── README.md
│
├── crawler.py                    # rule.hansung.ac.kr 크롤러 (HWP·HWPX 첨부 추출 포함)
├── make_rules_json.py            # history → 최신판 rules.json 변환
├── build_db.py                   # history → PostgreSQL 적재 (청크 + 임베딩)
├── patch_codes.py                # 규정 코드(1-0-1) 패치 (구버전, 옵션)
│
├── server.py                     # FastAPI 메인 — 모든 API
├── routers/
│   ├── __init__.py
│   └── teacher.py                # /conflict/, /export/pdf, /export/docx
│
├── index.html                    # 메인 — 챗봇 + 규정 목록 (사용자용)
├── upload.html                   # 관리자 4탭 페이지 (추가/개정/일괄치환/충돌분석)
├── login.html                    # 관리자 로그인
├── HSU_logo.png
│
├── hansung_rules.json            # 규정 목록용 (최신판 315편)
├── hansung_rules_history.json    # 챗봇/개정용 (1,600여 버전 포함)
├── dept_phones.json              # 부서 직통번호 매핑 (79개 부서)
│
├── uploads/                      # 업로드된 규정 파일 로컬 백업
└── .revision_backup/             # 개정/일괄치환 백업 (되돌리기용)
```

---

## 각 파일 역할

### crawler.py
- 규정관리시스템 크롤링 (`lawDetail.do` → `lawFullView.do` → `lawFullContent.do` 3단계)
- `<div class="JO">` / `<div class="addenda">` 구조로 본문 정확히 파싱 (UI 노이즈 제외)
- `javascript:fileDown(SEQ,'ori')` 패턴 감지 → `POST /lmxsrv/fileDown.do` 로 첨부파일 다운로드
- HWP(pyhwp CLI) / HWPX(ZIP+XML) / PDF(pdfplumber) / DOCX(python-docx) 텍스트 자동 추출
- 첨부파일 텍스트는 `attachment_text` 필드에 별도 저장 (본문 오염 방지)
- SEQ 1~1,500 + SEQ_HISTORY 모두 순회 → 모든 개정 버전 수집
- 결과: `hansung_rules_history.json` (315 규정 / 1,618 버전 / 255개 개정이력)
- 중간 저장 지원 → 재실행 시 이어서 진행
- 쿠키 만료 시 [쿠키 갱신](#쿠키-갱신-방법-크롤링-세션-만료-시) 참고

### make_rules_json.py
- `hansung_rules_history.json`에서 각 규정의 **최신 버전만** 추려 `hansung_rules.json` 생성
- 규정 목록 페이지(`/rules`)가 사용
- 실행 전 기존 파일 자동 백업

### build_db.py
- history JSON을 읽어 조항(제N조) 단위로 청크 분할
- `paraphrase-multilingual-MiniLM-L12-v2` 로컬 임베딩 (384차원)
- Docker PostgreSQL의 `rule_chunks` 테이블에 일괄 적재
- 첨부파일 텍스트, 개정이력 메타 청크도 함께 저장
- 완료 후 약 11,000+ 청크

### server.py (FastAPI 메인)

**정적 파일**
- `GET /` → index.html
- `GET /login-page` → login.html
- `GET /upload` → upload.html
- `GET /HSU_logo.png`, `GET /health`

**규정 검색 (사용자)**
- `GET /rules` → 전체 규정 목록 (편별 분류 + 업로드 규정 통합)
- `POST /query` → **벡터 + 키워드 하이브리드 검색** → Groq 답변 생성
  - 멀티턴 대화 지원
  - 답변에서 담당 부서명 자동 추출 → `dept_phones.json` 매칭 → 직통번호 반환
  - 연관 질문 4개 자동 추출(부족하면 fallback)
  - "개정 비교" 키워드 감지 시 `get_version_diff()`로 diff 컨텍스트 추가
- `POST /search-rules` → 규정 목록 키워드 검색 (본문 + 첨부파일 내용 포함)
- `POST /diff` → 버전 비교 모달용 조 단위 글자 diff 데이터

**관리자 인증 (JWT, .env 기반)**
- `POST /login` → 아이디/비밀번호 검증 → JWT 토큰 발급 (12시간 유효)

**규정 추가 (JWT 필요)**
- `POST /upload-regulation` → 파일 → 텍스트 추출 → AI 1~8편 분류 → 임베딩 → DB 저장
- `GET /uploaded-rules` → 업로드된 규정 목록
- `DELETE /uploaded-rules/{filename}` → 업로드 규정 즉시 삭제

**규정 개정 (JWT 필요) — history.json 기반**
- `GET /revisable-rules` → 개정 대상 규정 목록 (최신 버전 기준)
- `GET /revisable-rules/{seq}` → 특정 규정 최신 버전 본문 조회
- `GET /rule-articles/{seq}` → 조 목록 (조 단위 개정용)
- `GET /rule-articles/{seq}/{index}` → 특정 조 본문
- `POST /revise-regulation` → **전체 개정** — 최신 버전 content 덮어쓰기 + `revisions[]`에 날짜 기록
- `POST /revise-article` → **조 단위 개정** — 조 머리글 끝에 `(개정 YYYY-MM-DD)` 자동 부착 + 이력 기록
- `POST /extract-article-revision` → 개정안 파일 업로드 → AI가 해당 조 개정(안) 본문만 자동 추출
- `POST /format-check` → 한성대 규정 표준 형식 위반 자동 검출 (snippet/kind/advice 반환)

**단어 일괄 치환 (JWT 필요)**
- `POST /word-search` → 본문에 특정 단어가 들어간 모든 규정 검색 (인증 불필요)
- `POST /bulk-replace/preview` → 치환 전 미리보기 (옛 단어/새 단어/문맥 표시)
- `POST /bulk-replace/apply` → 선택 규정만 일괄 치환 + 단일 batch 백업

**되돌리기 (JWT 필요)**
- `GET /revision-backups` → 백업 목록 (최신순)
- `POST /revision-rollback` → 백업으로 JSON + DB 둘 다 복원
  - 단일 규정(전체/조 단위) / 일괄 치환 batch 모두 지원

### routers/teacher.py

**충돌 분석 — `POST /conflict/`** (재작성됨)

새 규정 초안 업로드 → 4단계 분석:
1. **PDF 깨짐 검사** — 한글 비율 / 짧은 토큰 반복률로 스캔본 PDF 자동 감지 (실패 시 사용자에게 변환 안내)
2. **의미있는 키워드 추출** — 한글 2~8자 토큰, 50개 불용어 제외, 빈도순
3. **핵심 규정 식별** — 문서 머리에서 "○○ 규정" 패턴 → DB title 매칭 (fallback: 키워드 점수 최다)
4. **AI 비교** — 핵심 규정 전체 조항(최대 30개 × 1,500자) + 다른 규정 보조 청크를 컨텍스트로 제공
   - "추상적·뻔한 표현 금지" 프롬프트로 구체적 비교만 강제
   - 결과 후처리: "충돌 가능성", "괴리", "일관성 부족" 같은 두루뭉술한 issue 자동 필터링

**답변 내보내기**
- `POST /export/pdf` → reportlab + 한글 폰트 자동 탐색 (Windows malgun.ttf → Linux NanumGothic → Mac AppleGothic)
- `POST /export/docx` → python-docx + 맑은 고딕 강제 적용

### dept_phones.json
- 한성대 행정부서 79개 → 직통번호 매핑
- 챗봇 답변 시 부서명 → 직통번호 자동 매칭 (예: 학사운영팀 → 4219)

### index.html (메인 페이지)

**챗봇 UI**
- 헤더: 풀와이드 그라데이션 배경, 좌측 정렬 큰 글자(48px), 우측 한성대 로고 150px
- 채팅 컨테이너 880px 가운데 정렬 (메인은 풀와이드)
- 사용자 말풍선: 푸른 그라데이션 우측 정렬
- AI 답변: 평문 + **글자 단위 타이핑 애니메이션** + 깜빡이 커서
- 답변 부가정보(좌측선 정렬):
  - 참조 조항 (인용된 조 번호만, 중복 제거)
  - 담당부서 카드 (부서명 + 직통번호)
  - 💡 연관 질문 4개 (항상 4개 보장, AI 부족 시 fallback)
  - PDF / Word 내보내기 / 버전 비교 (개정 질문일 때만)
- **입력창**: 화면 하단 `position: fixed` 고정, 50×50 정사각 전송 버튼, 큰 화살표(26px)
- **빈 화면**: "반가워요!" + 5개 추천 카드 (수강신청·징계·장학금·휴학·졸업)
- 우측 떠다니는 ↑/↓ 스크롤 점프 버튼
- 사이드바: 대화 이력 (localStorage 30개), "+ 새 질문" 버튼, 호버 시 ✕ 삭제

**규정 목록 탭**
- 검색창 하나로 통합 (규정명 + 본문 + 첨부 동시 검색)
- 검색어 없을 때 → 편별 분류 트리
- 검색어 입력 시 → 일치 규정만 + 키워드 빨간색 하이라이트

### upload.html (관리자 페이지)

4탭 구조:

**➕ 규정 추가**
- 파일 드래그앤드롭, 여러 파일 동시 업로드
- 파일별 실시간 상태 + 전체 진행바
- 업로드된 규정 목록 + 삭제 버튼

**✏️ 규정 개정** (좌우 2단 그리드)
- 좌측: 규정 검색 + 목록 → 클릭하여 선택
- 우측:
  - 전체 개정 / 조 단위 개정 탭
  - 조 단위 → 조 목록 → 클릭하여 선택 → 현재 본문 표시
  - 텍스트 직접 편집 OR 개정안 파일 업로드 → AI 자동 추출
  - **✨ AI 형식 검사** 버튼 → 표준 형식 위반 단어 본문에 하이라이트
  - 개정 적용 시 자동 백업 → 사이드바에 "되돌리기" 표시

**🔁 일괄 치환**
- 바꿀 단어 / 새 단어 입력 → 미리보기
- 결과: 각 규정 카드 + 조항별 문맥 + **옛 단어 회색 취소선 / 새 단어 빨강 볼드**
- 체크박스로 적용 규정 선택 → 한 번에 적용 → 단일 batch 백업 (한 번에 되돌리기)

**⚡ 충돌 분석**
- 클릭/드래그 업로드 영역
- 결과 카드: 파일명 + 충돌 N건 + 요약 + 항목별 심각도(높음/보통/낮음) + 권고사항
- 깨진 PDF는 분석 전 자동 안내

### login.html
- 관리자 로그인 페이지
- 서버 `/login` 호출 → JWT 토큰 localStorage 저장 → `/upload` 이동
- 이미 로그인된 경우(유효 토큰) 자동 리다이렉트

---

## .env 설정

```env
GROQ_API_KEY=gsk_여기에_Groq_키
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules

# 관리자 계정 (미설정 시 admin / 1234)
ADMIN_ID=admin
ADMIN_PW=1234

# JWT 서명 키 (32자 이상 권장 — 짧으면 서버가 자동 생성하지만 재시작 시마다 토큰 무효화됨)
SECRET_KEY=랜덤32자이상문자열
```

Groq API 키 발급: https://console.groq.com → API Keys → Create (무료)

---

## 실행 순서

### Step 1. `.env` 파일 생성 (위 양식대로)

### Step 2. 크롤링 (최초 1회)

```powershell
python crawler.py
```
- 약 30~50분 소요 (HWP 첨부파일 다운로드 포함)
- 결과: `hansung_rules_history.json` (~30MB)
- 쿠키 만료 시 [쿠키 갱신](#쿠키-갱신-방법-크롤링-세션-만료-시) 참고

### Step 3. 최신판 추출

```powershell
python make_rules_json.py
```
- `hansung_rules_history.json` → `hansung_rules.json` (~5MB)
- 규정 목록 페이지가 사용

### Step 4. 벡터 DB 구축

```powershell
python build_db.py
```
- 첫 실행 시 임베딩 모델 자동 다운로드 (~500MB, 1회)
- Docker `hansung-db` 컨테이너 실행 중이어야 함
- 완료 후 약 11,000+ 청크 생성

### Step 5. 서버 실행

```powershell
uvicorn server:app --reload --port 8080
# 또는
python server.py
```

### Step 6. 접속

```
http://127.0.0.1:8080
```

---

## 규정 업데이트 방법 (관리자)

1. 메인 페이지 헤더의 **🔐 관리자** 클릭 → 로그인
2. 4탭 중 원하는 작업 선택:
   - **새 규정 등록**: ➕ 규정 추가 → 파일 업로드
   - **기존 규정 내용 변경**: ✏️ 규정 개정 → 좌측에서 검색·선택 → 우측에서 편집 → 적용
   - **부서명 일괄 변경**: 🔁 일괄 치환 → 단어 입력 → 미리보기 → 선택 적용
   - **외부 문서 사전 검토**: ⚡ 충돌 분석 → 파일 드래그
3. 모든 개정 작업은 자동 백업 → 사이드바 백업 목록에서 한 번에 되돌리기

---

## 쿠키 갱신 방법 (크롤링 세션 만료 시)

1. Chrome에서 `rule.hansung.ac.kr` 접속 후 아무 규정 클릭
2. F12 → Network 탭 → F5 새로고침
3. `lawDetail.do` 요청 클릭 → Request Headers → Cookie 값 전체 복사
4. `crawler.py`의 `COOKIES` 딕셔너리 교체 후 재실행

---

## DB 연결 정보 (Docker)

| 항목 | 값 |
|------|-----|
| Host | localhost |
| Port | 5432 |
| DB명 | hansungrules |
| User | postgres |
| 테이블 | rule_chunks |
| 임베딩 모델 | paraphrase-multilingual-MiniLM-L12-v2 |
| 벡터 차원 | 384 |
| 총 청크 수 | 약 11,000+ (HWP 첨부 + 개정이력 메타 포함) |

### rule_chunks 테이블 구조

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | TEXT | 고유 식별자 (`r{seq}_h{hist}_{art}` 패턴) |
| rule_title | TEXT | 규정명 |
| seq | TEXT | 규정 SEQ (rule_id) |
| article | TEXT | 조항명 (`제N조 (...)`, 또는 `'개정이력'`) |
| department | TEXT | 담당부서 |
| url | TEXT | 원문 링크 (업로드 규정: `upload://파일명`) |
| content | TEXT | 조항 내용 (HWP 첨부 텍스트 포함) |
| embedding | VECTOR(384) | 임베딩 벡터 |

---

## 코드 공유 시 주의사항

- **`.env`는 절대 git에 올리지 말 것** — `.gitignore`에 포함됨
- 각자 Groq API 키 발급 필요 (무료, https://console.groq.com)
- 각자 Docker Desktop 설치 + 컨테이너 실행 필요
- 첫 실행 시 임베딩 모델 자동 다운로드 (인터넷 연결 필요)

---

## 알려진 제약

- **편(編) 분류**: `hansung_rules.json`의 `category`가 빈 값인 규정 다수 → 규정 목록에서 대부분 "기타"로 표시됨. 크롤러를 보강해 사이트 좌측 트리(제1~8편)와 매핑 후 재크롤링하면 해결.
- **스캔본 PDF**: 텍스트 레이어 없는 스캔본은 추출 불가 (충돌 분석에서 자동 안내). 향후 Claude API 등 멀티모달 모델 도입으로 해결 가능.
- **Groq 무료 티어**: 분당 호출 제한 있음. 동시 사용자 많아지면 유료 플랜 고려.
- **충돌 분석 컨텍스트**: 현재 핵심 규정 30조항 × 1,500자까지 비교. 더 긴 규정은 일부 잘림.

---

## 변경 이력 (주요)

- **v2 (현재)**: history.json 기반 개정 기능 마이그레이션 / 충돌 분석 관리자 페이지로 이동 + 정확도 대폭 개선 / 챗봇 UI 대화형 전면 개편 / 추천 카드 / 입력창 하단 고정 / 일괄 치환 / AI 형식 검사 / 단어 일괄 치환 / 부서별 직통번호 매핑 / dept_phones.json 외부화
- **v1**: 단일 규정 검색·답변, 교직원/학생 모드, 충돌 분석 기본