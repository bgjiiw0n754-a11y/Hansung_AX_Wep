# Hansung_AX

> **2026 한성대학교 AX 프론티어 공모전 출품작**

# 한성대학교 규정 마스터 AI

한성대학교의 **모든 규정(315편 · 1,618개 버전)** 을 학습한 RAG(Retrieval-Augmented Generation) 챗봇입니다. 학생·교직원이 자연어로 질문하면 근거 조항과 담당부서·직통번호까지 함께 답변하고, **관리자는 회의자료(HWP·PDF) 한 장만 올리면 AI가 개정안을 자동 추출**해서 미리보기 비교 후 한 번에 반영할 수 있습니다.

---

## 핵심 기능

| 기능 | 설명 |
|---|---|
| **규정 검색·답변** | 자연어 질문 → 관련 조항 검색 → 근거 조항·담당부서·전화번호 포함 답변 (SSE 스트리밍) |
| **편(編)별 규정 목록** | 제1편 학교법인 ~ 제8편 학생군사교육단까지 사이트 트리 그대로 분류 |
| **개정 이력 추적** | 모든 규정의 과거 버전 보관 — 신구조문 대비, 조 단위 변경 내용 추출 |
| **규정 추가** | PDF/DOCX/HWP/HWPX 업로드 → 자동 텍스트 추출 → 청크화 → 임베딩 → DB 등록 |
| **규정 개정** | 전체/조 단위 개정 모두 **미리보기 모달**에서 좌(현행) vs 우(개정안)을 **어절+글자 단위 하이브리드 diff**로 비교 후 적용 |
| **회의록 기반 AI 개정** | **새 기능** · 회의자료(HWP·PDF) 또는 텍스트 직접 입력 → AI 4단계 파이프라인이 자동 분석 → 한 안건 = 한 카드로 변경 사항 정리 |
| **일괄 치환** | "기획처 → 글로컬상생홍보팀" 같은 전 규정 동시 변경. 미리보기 후 영향 받는 규정 선택해 적용 |
| **활동 로그** | 사이드바에 추가/개정/일괄치환 활동이 시간순으로 표시. **➕ 추가는 🗑 삭제, ✏️ 개정은 ↩️ 되돌리기** 한 번에 가능 |
| **충돌 분석** | 신규/개정 규정 파일 업로드 → 기존 규정과의 모순·중복을 Claude가 분석 |
| **AI 형식 검사** | 작성한 규정이 한성대 표준 형식(`제 N 조`, `①`, `1.` 등)에 맞는지 깐깐히 점검 |

---

## 회의록 기반 AI 개정 — 4단계 파이프라인

이번 버전의 가장 큰 변화. 회의자료를 올리면 AI가 다음 단계를 자동 수행합니다:

```
회의자료 업로드 (또는 텍스트 직접 입력)
   ↓
① AI가 양식 판단      — 표 양식인가, 줄글 양식인가?
   ↓
② 1차: 규정 매칭      — 어떤 규정의 개정인지 history.json과 fuzzy 매칭
② 2차: 개정안만 추출  — ★ 현행 본문은 절대 건드리지 않음. 시스템에 정답이 있음.
   ↓
③ 시스템에서 현행 자동 로드 — history.json의 최신 버전 본문
   ↓
④ 통합 미리보기       — [시스템 현행 전체] vs [AI 추출 개정안 합성본]
                       하이브리드 diff로 변경된 부분만 강조
```

### 보조 파싱 — HWP 표 구조 직접 분리

AI가 양식을 판단하기 전에 서버가 먼저 표 구조를 분석합니다:

1. **`hwp5html`**로 HWP → HTML 변환 → `<table><tr><td>` 그대로 보존 → "현행규정 | 개정(안)" 헤더 표를 골라 셀별 좌/우 분리
2. **`hwp5proc xml`** 폴백 — XML 텍스트 노드 추출
3. **텍스트 패턴 폴백** — `제 N 조`가 두 번 등장하는 패턴으로 좌/우 분리
4. 분리된 좌/우 셀이 AI 프롬프트에 명시적으로 전달돼서 AI가 헷갈릴 일 없음

### 통합 카드 (한 안건 = 한 카드)

조 단위로 카드를 여러 개 띄우지 않고, **안건 단위로 묶어서** 보여줍니다:

- 시스템 현행을 조 단위로 분리
- AI가 추출한 조마다 같은 조를 교체
- 회의록에 없는 조는 시스템 현행 그대로 유지 (절대 사라지지 않음)
- 신설된 부 칙·신규 조는 끝에 추가
- 미리보기는 시스템 현행 전체 vs 합성된 개정안 전체

---

## 어절+글자 단위 하이브리드 Diff

기존 글자 단위 diff는 `(2026.4.10.)` ↔ `(2026.0.00.)` 같은 토큰을 한 자씩 잘라서 `(2026.40.100.)`처럼 보였습니다. 이번에 **하이브리드 diff**로 개선:

1. **어절 단위로 먼저 diff** (공백 기준 단어 분리)
2. **숫자·구두점 섞인 토큰** (날짜·코드 등) → **통째로** 빨강/파랑
3. **순한글 어절** (조사 변화 등) → 어절 안에서 **글자 단위로 더 세밀하게**
4. 인접한 같은 종류 세그먼트는 자동 병합

### 검증된 결과

| 입력 | 결과 |
|---|---|
| `(2026.4.10.)` ↔ `(2026.0.00.)` | **통째로** 빨강 / 파랑 |
| `촉진시키는` ↔ `촉진하는` | **글자 단위** `시키`/`하` |
| `이 연구원은` ↔ `본 연구원은` | 한 글자 `이`/`본` |

---

## 활동 로그 사이드바

우측에 고정된 사이드바에서 모든 관리 활동을 깃허브 커밋 피드 스타일로 확인:

| 종류 | 아이콘 | 색상 | 액션 |
|---|---|---|---|
| 규정 추가 | ➕ | 초록 | 🗑 삭제 (DB + 파일 제거) |
| 전체 규정 개정 | ✏️ | 파랑 | ↩️ 되돌리기 |
| 조 단위 개정 | 📌 | 파랑 | ↩️ 되돌리기 |
| 일괄 치환 | 🔁 | 호박 | ↩️ 되돌리기 |

시간순 통합 피드, 사이드바 토글 가능(localStorage 저장).

---

## AI 스택

| 단계 | 모델 | 역할 |
|---|---|---|
| **임베딩** | Upstage `solar-embedding-1-large` (4096차원) | 질문·문서를 한국어 특화 벡터로 변환 |
| **재순위화** | Voyage `rerank-2` | 임베딩 후보 중 진짜 관련 조항만 선별 |
| **생성** | Anthropic `claude-sonnet-4-5` | 답변 + 충돌 분석 + 형식 검사 + 회의록 분석 + 텍스트 정돈 |
| **Fallback** | Groq `llama-4-scout-17b` | Claude 장애 시 자동 백업 |

### 검색 흐름

```
질문 입력
   ↓
[1] Claude 키워드 확장 (5~10개 동의어·관련 용어)
   ↓
[2] Upstage 임베딩(4096차원) → DB pgvector 검색 (TOP 30 후보)
   ↓
[3] 키워드 LIKE 보강 (놓친 조항 추가)
   ↓
[4] Voyage rerank → 진짜 관련 8개 선별
   ↓
[5] 부서 매핑 + 컨텍스트 구성
   ↓
[6] Claude SSE 스트리밍 답변 (글자 단위 실시간 표시)
```

---

## 🛠 기술 스택

| 영역 | 기술 |
|---|---|
| **백엔드** | FastAPI · psycopg2 · python-multipart · PyJWT |
| **DB** | PostgreSQL 16 + `pgvector` 확장 (4096차원 벡터) |
| **프론트** | 정적 HTML + Vanilla JS (Server-Sent Events) |
| **문서 파싱** | pdfplumber · python-docx · pyhwp (`hwp5txt` · `hwp5proc xml` · `hwp5html`) · lxml · BeautifulSoup4 |
| **크롤러** | requests · BeautifulSoup4 |
| **컨테이너** | Docker (PostgreSQL) |

---

## 프로젝트 구조

```
HSU/
├── server.py                  # FastAPI 메인 (모든 엔드포인트)
├── routers/
│   └── teacher.py             # 충돌 분석 + PDF/Word 내보내기
├── crawler.py                 # rule.hansung.ac.kr 크롤러
├── make_rules_json.py         # history → 최신판 hansung_rules.json
├── build_db.py                # Upstage 임베딩 + DB 적재
├── migrate_v3.sql             # DB 마이그레이션 (384 → 4096차원)
├── index.html                 # 메인 (챗봇 + 규정 목록)
├── upload.html                # 관리자 (추가/개정/회의록/일괄치환/충돌분석 + 활동 로그)
├── login.html                 # 관리자 로그인
├── hansung_rules_history.json # 315 규정 × 평균 5버전
├── hansung_rules.json         # 최신판만 추린 버전
├── dept_phones.json           # 79개 부서 직통번호
├── revision_backups/          # 개정 자동 백업 (롤백용)
├── requirements.txt
└── .env                       # API 키 + DB URL (gitignore)
```

---

## 설치 및 실행

### 1. 사전 요구사항
- Python 3.11+
- Docker Desktop
- Windows: `pyhwp` 설치 후 `hwp5txt --help`, `hwp5proc --help`, `hwp5html --help` 모두 동작 확인

### 2. 저장소 클론
```bash
git clone https://github.com/sumiiniee/Hansung_AX.git
cd Hansung_AX
```

### 3. 환경 변수 설정 (`.env`)
```env
ANTHROPIC_API_KEY=sk-ant-...
UPSTAGE_API_KEY=up_...
VOYAGE_API_KEY=pa-...
GROQ_API_KEY=gsk_...                  # Fallback (선택)
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules
ADMIN_ID=admin
ADMIN_PW=원하는비밀번호
SECRET_KEY=랜덤_32자_이상_문자열
```

### 4. 패키지 설치
```bash
pip install -r requirements.txt
```

### 5. PostgreSQL 컨테이너
```bash
docker run -d --name hansung-db \
  -e POSTGRES_PASSWORD=비밀번호 \
  -e POSTGRES_DB=hansungrules \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 6. DB 스키마 마이그레이션
```bash
docker cp migrate_v3.sql hansung-db:/tmp/
docker exec -it hansung-db psql -U postgres -d hansungrules -f /tmp/migrate_v3.sql
```

### 7. 데이터 준비
- **옵션 A (빠름)**: 저장소의 `hansung_rules_history.json` 그대로 사용
- **옵션 B (1~2시간)**: `python crawler.py` (쿠키 갱신 후) → `python make_rules_json.py`

### 8. DB 빌드 (15~30분)
```bash
python build_db.py
```

### 9. 서버 실행
```bash
python server.py
# 또는: uvicorn server:app --reload --port 8000
```

- 메인: `http://127.0.0.1:8000`
- 관리자: `http://127.0.0.1:8000/upload` (로그인 필요)

---

## 사용 예시

### 학생/교직원 — 챗봇

추천 카드 클릭 또는 직접 질문:
- "수강신청 방법을 알려주세요"
- "휴학 가능한 기간이 어떻게 되나요?"
- "미래플러스대학 학사운영 규정 개정 이력이 어떻게 되나요?"

답변에는 본문(SSE 스트리밍) + 📞 담당부서·직통번호 + 참조 조항 카드 + 🔍 버전 비교(개정 비교 질문일 때) + 이어서 물어보기 + ⬇ PDF/Word 내보내기가 함께 나옵니다.

### 관리자 — 규정 관리

`/upload` 페이지에서 5개 탭:

**① ➕ 규정 추가**
PDF/DOCX/HWP 업로드 → 자동 청크화·DB 등록 → 활동 로그에 ➕ 표시

**② 규정 개정** (전체/조 단위)
- 본문 직접 입력 또는 개정 파일 업로드 (조 단위는 AI가 개정안 자동 추출)
- **🔍 미리보기** → 좌(현행) vs 우(개정안) 하이브리드 diff 모달
- **이대로 적용** → 옛 버전 자동 백업 후 신 버전 등록

**③ 회의록 기반**
- 입력 방식 토글: 📎 파일 / ✏️ 직접 입력
- 파일: HWP·PDF·DOCX·HWPX (표 양식 + 줄글 양식 다 지원)
- 직접 입력: 텍스트 영역 + 선택적 대상 규정 지정
- 결과: 안건당 카드 1개 — "📌 전체 규정 개정 — N개 조 변경/신설"
- 카드 안: 💡 사유 · 🔵 변경/신설 목록 · ▸ AI 추출 본문 보기·수정 · 🔍 미리보기

**④ 일괄 치환**
"옛 단어 → 새 단어" 미리보기 → 영향 받는 규정 체크박스로 선택 → 적용

**⑤ 충돌 분석**
신규 파일 업로드 → Claude가 기존 315편과 비교 → 모순·중복 보고서

---

## 데이터 현황

| 항목 | 수치 |
|---|---|
| 규정 수 | **315편** |
| 총 버전 수 | **1,618개** |
| 첨부 텍스트 | **315건** |
| DB 청크 | **약 43,000개** |
| 부서 매핑 | **79개** 부서 직통번호 |
| 편 분류 | **315/315** (100%) |

---

## 보안 · 정확성

- **JWT 인증**: 관리자 토큰 24시간 유효, 매 요청 서버 검증
- **부서명 검증**: AI 임의 부서명 → 실제 source 부서명으로 자동 교체
- **출처 인용 강제**: 인용 없는 조항은 참조 카드에서 자동 제거
- **개정 미리보기**: 실제 DB 반영 전 하이브리드 diff로 확인 → 오타·실수 차단
- **자동 백업**: 모든 개정·치환은 `revision_backups/`에 보관 → 활동 로그에서 1-click 롤백
- **회의록 분석의 신뢰성**: AI에게 **개정안만** 추출시키고 현행은 시스템에서 가져옴 → "AI가 현행을 잘못 가져오는" 실수 자체가 발생할 수 없음
- **업로드 규정 자동 백필**: DB의 `upload://*` 규정이 history.json에 누락돼 있으면 회의록 분석 직전에 자동 등록 → 회의록 매칭 후보로 포함

---

## 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/query-stream` | 챗봇 답변 (SSE) |
| POST | `/query` | 챗봇 답변 (JSON, 호환용) |
| POST | `/diff` | 버전 간 하이브리드 diff |
| GET | `/rules` | 편별 규정 목록 |
| POST | `/upload` | 규정 추가 |
| POST | `/revise-preview` | 전체 개정 미리보기 |
| POST | `/revise-regulation` | 전체 개정 적용 |
| POST | `/revise-article-preview` | 조 단위 개정 미리보기 |
| POST | `/revise-article` | 조 단위 개정 적용 |
| POST | `/extract-meeting-revisions` | **회의록 파일 분석 (AI 4단계)** |
| POST | `/extract-meeting-revisions-text` | **회의록 직접 입력 분석** |
| POST | `/bulk-replace/preview` | 일괄 치환 미리보기 |
| POST | `/bulk-replace/apply` | 일괄 치환 적용 |
| POST | `/conflict/analyze` | 충돌 분석 |
| POST | `/format-check` | AI 형식 검사 |
| GET | `/revision-backups` | **활동 로그 통합 피드** (개정·치환·추가) |
| POST | `/revision-rollback` | 개정·치환 되돌리기 |
| DELETE | `/uploaded-rules/{filename}` | 업로드 규정 삭제 |

---

## 트러블슈팅

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError: anthropic` | `pip install anthropic voyageai` |
| 크롤러 빈 페이지 | `crawler.py` 73줄 `COOKIE_STRING` 새 쿠키로 갱신 |
| `hwp5txt`/`hwp5proc`/`hwp5html` 없음 | `pip install pyhwp` |
| HWP 표가 `<표>`로만 나옴 | `hwp5proc xml` 폴백이 자동 동작 — 그래도 안 되면 텍스트 패턴 파서가 잡음 |
| 회의록 매칭 실패 | 업로드된 규정이 history에 없을 수 있음. 분석 직전 자동 백필이 돌지만 안 되면 서버 재시작 |
| 회의록 분석 결과가 이상 | 카드의 "▸ AI 추출 본문 보기·수정"으로 직접 수정 가능 |
| DB 빌드 `ON CONFLICT` 에러 | `TRUNCATE TABLE rule_chunks;` 후 재시도 |

---

## 변경 이력

### v3.5 (2026.05) — 회의록 자동화

- **회의록 기반 AI 개정** 추가
  - 4단계 파이프라인: 양식 판단 → 규정 매칭 → 개정안 추출 → 시스템 현행과 비교
  - AI에게 **개정안만** 추출시키고 현행은 시스템에서 자동 로드 → "AI가 현행을 개정안으로 잘못 가져오는" 실수 원천 차단
  - 파일 업로드 모드 + 직접 입력 모드 (선택적 대상 규정 지정)
  - 한 안건 = 한 카드로 통합. 변경된 조 N개 + 신설 부 칙 한눈에
- **HWP 표 파싱 강화**
  - `hwp5html` → `<table><tr><td>` 직접 파싱 (1순위)
  - `hwp5proc xml` → XML 텍스트 노드 추출 (2순위)
  - 텍스트 패턴 폴백 — `제 N 조`가 두 번 등장하는 패턴
- **어절+글자 하이브리드 Diff**
  - 숫자·구두점 토큰은 통째로, 한글 어절은 글자 단위
  - `(2026.4.10.) → (2026.0.00.)` 같은 변경이 깔끔하게 보임
- **활동 로그 사이드바**
  - 추가/개정/일괄치환 시간순 통합 피드
  - 종류별 아이콘·색상 (➕ 초록 / ✏️📌 파랑 / 🔁 호박)
  - 추가는 🗑 삭제, 개정·치환은 ↩️ 되돌리기
- **업로드 규정 자동 백필** — DB의 `upload://*` 누락분 자동 등록
- **AI 텍스트 정돈** — PDF/HWP 추출 시 어긋난 줄바꿈·공백을 AI가 함께 정리

### v3 (2026.05)
- AI 스택 전면 교체: sentence-transformers + Groq → Upstage + Voyage + Claude
- 임베딩 차원: 384 → 4096 (한국어 특화)
- SSE 스트리밍, 편 분류, 첨부 텍스트 추출
- 충돌 분석 Claude 전환, 형식 검사 강화
- 개정 미리보기 모달 (글자 단위 diff)

### v2 (2026.02)
- 멀티턴 대화, 개정 이력 추적
- 관리자 페이지 기본 형태
- AI 형식 검사 (Groq)

### v1 (2026.01)
- 단일 턴 RAG 챗봇
- pgvector + sentence-transformers
- 정적 규정 목록

---

## 기여

이슈/PR 환영합니다.

## 라이선스

학내 사용 + 공모전 제출용. 상업적 이용 금지.

---

**2026 한성대학교 AX 프론티어 공모전**