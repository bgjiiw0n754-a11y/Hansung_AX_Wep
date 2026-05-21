# Hansung_AX

> **2026 한성대학교 AX 프론티어 공모전 출품작**

# 한성대학교 규정 마스터 AI

한성대학교의 **모든 규정(315편 · 1,618개 버전)** 을 학습한 RAG(Retrieval-Augmented Generation) 챗봇입니다. 학생·교직원이 자연어로 질문하면 근거 조항과 담당부서·직통번호까지 함께 답변합니다.

---

## ✨ 핵심 기능

| 기능 | 설명 |
|---|---|
| 🔍 **규정 검색·답변** | 자연어 질문 → 관련 조항 검색 → 근거 조항·담당부서·전화번호 포함 답변 (SSE 스트리밍) |
| 📚 **편(編)별 규정 목록** | 제1편 학교법인 ~ 제8편 학생군사교육단까지 사이트 트리 그대로 분류 |
| 📜 **개정 이력 추적** | 모든 규정의 과거 버전 보관 — 신구조문 대비, 조 단위 변경 내용 추출 |
| ➕ **규정 추가** | PDF/DOCX/HWP/HWPX 업로드 → 자동 텍스트 추출 → 청크화 → 임베딩 → DB 등록 |
| ✏️ **규정 개정** | 전체/조 단위 개정 모두 **미리보기 모달**에서 좌(현행) vs 우(개정안)을 **글자 단위 diff**로 비교 후 적용. 파일 업로드 시 AI가 개정안 자동 추출 |
| 🔁 **일괄 치환** | "기획처 → 글로컬상생홍보팀" 같은 전 규정 동시 변경. 미리보기 후 적용 |
| ⚡ **충돌 분석** | 신규/개정 규정 파일 업로드 → 기존 규정과의 모순·중복을 Claude가 분석 |
| ✨ **AI 형식 검사** | 작성한 규정이 한성대 표준 형식(`제 N 조`, `①`, `1.` 등)에 맞는지 깐깐히 점검 |

---

## 🧠 AI 스택 (v3)

| 단계 | 모델 | 역할 |
|---|---|---|
| **임베딩** | Upstage `solar-embedding-1-large` (4096차원) | 질문·문서를 한국어 특화 벡터로 변환 |
| **재순위화** | Voyage `rerank-2` | 임베딩 후보 중 진짜 관련 조항만 선별 |
| **생성** | Anthropic `claude-sonnet-4-5` | 컨텍스트 기반 답변 + 충돌 분석 + 형식 검사 |
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
| **문서 파싱** | pdfplumber · python-docx · pyhwp (`hwp5txt`) · lxml |
| **크롤러** | requests · BeautifulSoup4 |
| **컨테이너** | Docker (PostgreSQL) |

---

## 📁 프로젝트 구조

```
HSU/
├── server.py                  # FastAPI 메인 (/query-stream, /diff, /rules, /upload, ...)
├── routers/
│   └── teacher.py             # 충돌 분석 + PDF/Word 내보내기
├── crawler.py                 # rule.hansung.ac.kr 크롤러 (편 분류 + 첨부 추출)
├── make_rules_json.py         # history → 최신판 hansung_rules.json 생성
├── build_db.py                # Upstage 임베딩 + DB 적재
├── migrate_v3.sql             # DB 마이그레이션 (384차원 → 4096차원)
├── index.html                 # 메인 (챗봇 + 규정 목록)
├── upload.html                # 관리자 (추가/개정/일괄치환/충돌분석)
├── login.html                 # 관리자 로그인
├── hansung_rules_history.json # 315 규정 × 평균 5버전 (개정 이력 포함)
├── hansung_rules.json         # 최신판만 추린 버전 (목록·검색용)
├── dept_phones.json           # 79개 부서 직통번호 매핑
├── requirements.txt
└── .env                       # API 키 + DB URL (gitignore)
```

---

## 🚀 설치 및 실행

### 1. 사전 요구사항

- Python 3.11+
- Docker Desktop
- Windows의 경우: `pyhwp` 설치 후 `hwp5txt --help` 동작 확인

### 2. 저장소 클론

```bash
git clone https://github.com/sumiiniee/Hansung_AX.git
cd Hansung_AX
```

### 3. 환경 변수 설정

`.env` 파일을 프로젝트 루트에 생성:

```env
# AI 키
ANTHROPIC_API_KEY=sk-ant-...
UPSTAGE_API_KEY=up_...
VOYAGE_API_KEY=pa-...
GROQ_API_KEY=gsk_...                  # Fallback (선택)

# DB
DATABASE_URL=postgresql://postgres:비밀번호@localhost:5432/hansungrules

# 관리자
ADMIN_ID=admin
ADMIN_PW=원하는비밀번호
SECRET_KEY=랜덤_32자_이상_문자열
```

### 4. 패키지 설치

```bash
pip install -r requirements.txt
```

### 5. PostgreSQL 컨테이너 실행

```bash
docker run -d --name hansung-db \
  -e POSTGRES_PASSWORD=비밀번호 \
  -e POSTGRES_DB=hansungrules \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

### 6. DB 스키마 마이그레이션 (v3)

```bash
docker cp migrate_v3.sql hansung-db:/tmp/
docker exec -it hansung-db psql -U postgres -d hansungrules -f /tmp/migrate_v3.sql
```

### 7. 데이터 준비

#### 옵션 A. 기존 데이터 사용 (빠름)

저장소에 포함된 `hansung_rules_history.json` (315편 / 1,618버전 / 첨부 315건)을 그대로 사용.

#### 옵션 B. 직접 크롤링 (1~2시간)

```bash
# 1) 크롤러 쿠키 갱신 (Chrome → F12 → Network → cookie 헤더 복사 → crawler.py 73줄)
# 2) 크롤링
python crawler.py
```

크롤러는 사이트 좌측 트리(`lawTree.do?LAWGROUP=1`)에서 1~8편 분류를 자동으로 가져와 각 규정에 매핑합니다.

### 8. 최신판 JSON 생성

```bash
python make_rules_json.py
```

### 9. DB 빌드 (15~30분)

```bash
python build_db.py
```

Upstage `solar-embedding-1-large-passage`로 모든 청크(약 43,000개)를 4096차원 벡터화하여 PostgreSQL pgvector에 적재합니다.

### 10. 서버 실행

```bash
python server.py
```
또는
uvicorn server:app --reload --port 8080

브라우저에서:
- 메인: `http://127.0.0.1:8080`
- 관리자: `http://127.0.0.1:8080/upload` (로그인 필요)

---

## 💬 사용 예시

### 학생/교직원 — 챗봇

추천 카드 클릭 또는 직접 질문 입력:

- "수강신청 방법을 알려주세요"
- "휴학 가능한 기간이 어떻게 되나요?"
- "미래플러스대학 학사운영 규정 개정 이력이 어떻게 되나요?"
- "징계 종류와 기준이 무엇인가요?"

답변에는 다음이 함께 표시됩니다:
- 본문 (실시간 SSE 스트리밍)
- 📞 담당부서 + 직통번호
- 참조 조항 카드 (클릭 시 원문 페이지로 이동)
- 🔍 버전 비교 (개정 비교 질문일 때) — 옛/새 버전을 글자 단위 diff로 표시
- 이어서 물어보기 (관련 질문 4개)
- ⬇ PDF / ⬇ Word 답변 내보내기

### 관리자 — 규정 관리

`/upload` 페이지에서:

1. **➕ 규정 추가**: PDF/DOCX/HWP 업로드 → 자동 청크화·DB 등록
2. **✏️ 규정 개정** (전체/조 단위):
   - 본문 입력 또는 개정 파일 업로드 (조 단위는 Claude가 개정안 자동 추출)
   - **🔍 미리보기** 클릭 → 좌(현행) vs 우(개정안)을 **글자 단위 diff** 모달로 비교
     - 좌: 삭제될 글자만 빨강 볼드
     - 우: 새로 추가될 글자 파랑 볼드 + 삭제될 글자 빨강 볼드(취소선)
   - **이대로 적용** → 옛 버전 자동 백업 후 신 버전 등록
3. **🔁 일괄 치환**: "옛 단어 → 새 단어" 미리보기 → 영향 받는 규정 선택 → 일괄 적용
4. **⚡ 충돌 분석**: 신규 파일 업로드 → Claude가 기존 315편과 비교 → 모순·중복 보고서

---

## 📊 데이터 현황

| 항목 | 수치 |
|---|---|
| 규정 수 | **315편** |
| 총 버전 수 | **1,618개** (개정 이력 포함) |
| 첨부 텍스트 | **315건** (HWP/PDF/DOCX/HWPX 추출 완료) |
| DB 청크 | **약 43,000개** (조 단위 + 전문) |
| 부서 매핑 | **79개** 부서 직통번호 |
| 편(編) 분류 | **315/315** (사이트 트리 100% 매핑) |

### 편별 분포

| 편 | 규정 수 |
|---|---|
| 제1편 학교법인 | 2 |
| 제2편 학칙 | 3 |
| 제3편 학사행정 | 213 |
| 제4편 부속기관 | 2 |
| 제5편 부설기관 | 12 |
| 제6편 위원회 | 58 |
| 제7편 산학협력단 | 24 |
| 제8편 학생군사교육단 | 1 |

---

## 🔐 보안 · 정확성

- **JWT 인증**: 관리자 토큰은 24시간 유효, 매 요청마다 서버 검증
- **부서명 검증**: AI가 답변에 임의 부서명을 적으면 → 실제 source의 부서명으로 자동 교체 → 잘못된 전화번호 안내 방지
- **출처 인용 강제**: 모든 답변에 인용 조항 번호 명시. 인용 없는 조항은 참조 카드에서 자동 제거
- **답변 후처리**: 마크다운 정리, 출처/부서 평문 라벨 제거, 본문 깔끔하게 표시
- **AI 형식 검사**: 실제 한성대 규정 본문 1,500자×3편을 샘플로 보여주며 검토 → 추상적 규칙만 줄 때보다 훨씬 깐깐
- **개정 미리보기**: 실제 DB 반영 전 글자 단위 diff로 확인 → 오타·실수 적용 차단. 적용 후에도 자동 백업으로 1-click 롤백

---

## ⚙ 주요 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/query-stream` | 챗봇 답변 (SSE 스트리밍) |
| POST | `/query` | 챗봇 답변 (일반 JSON, 호환용) |
| POST | `/diff` | 버전 간 글자 단위 diff |
| GET | `/rules` | 편별 규정 목록 |
| POST | `/upload` | 규정 추가 (관리자) |
| POST | `/revise-preview` | 전체 개정 미리보기 — 글자 단위 diff (관리자) |
| POST | `/revise-regulation` | 전체 개정 실제 적용 (관리자) |
| POST | `/revise-article-preview` | 조 단위 개정 미리보기 — 글자 단위 diff (관리자) |
| POST | `/revise-article` | 조 단위 개정 실제 적용 (관리자) |
| POST | `/bulk-replace` | 일괄 치환 (관리자) |
| POST | `/conflict/analyze` | 충돌 분석 (관리자) |
| POST | `/format-check` | AI 형식 검사 (관리자) |
| GET | `/revision-backups` | 개정 되돌리기 목록 (관리자) |
| POST | `/revision-rollback` | 개정 되돌리기 (관리자) |

---

## 🧪 트러블슈팅

| 증상 | 해결 |
|---|---|
| `ModuleNotFoundError: anthropic` | `pip install anthropic voyageai` |
| 크롤러 빈 페이지만 받음 | Chrome에서 새 쿠키 받아 `crawler.py` 73줄 `COOKIE_STRING` 갱신 |
| `hwp5txt` 명령 없음 | `pip install pyhwp` |
| DB 빌드 중 `ON CONFLICT` 에러 | 같은 id 중복 → `TRUNCATE TABLE rule_chunks;` 후 재시도 |
| Upstage rate-limit | 자동 재시도되며 정상 종료됨. 무료 티어 한도 주의 |
| 답변 부서가 틀림 | source의 실제 부서명으로 자동 교체되도록 v3에서 보강됨 |

---

## 📝 변경 이력

### v3 (2026.05)
- **AI 스택 전면 교체**: sentence-transformers + Groq → Upstage + Voyage + Claude
- **임베딩 차원**: 384 → 4096 (한국어 특화)
- **SSE 스트리밍**: 답변이 글자 단위로 실시간 표시 (체감 속도 5배)
- **편(編) 분류**: 사이트 좌측 트리(lawTree.do) 직접 파싱 → 315/315 매핑
- **첨부 텍스트 추출**: HWP/PDF/DOCX/HWPX 모두 본문에 통합
- **충돌 분석**: Claude로 전환 (한국어 추론 정확도↑)
- **형식 검사 강화**: 실제 한성대 규정 본문 샘플 + 구체적 수정안 강제
- **부서 매핑 보강**: 최빈값 + AI 답변 텍스트 보정 + DEPT_PHONE 부분 매칭
- **개정 미리보기 모달**: 전체/조 단위 개정 모두 적용 전 글자 단위 diff로 비교
  - 좌(현행): 삭제될 글자 빨강 볼드
  - 우(개정안): 새로 추가될 글자 파랑 볼드 + 삭제될 글자 빨강 볼드(취소선)
  - 상단에 추가/삭제 색 범례
  - "개정하기" 버튼 → "🔍 미리보기"로 통일, 모달 안 "이대로 적용"으로 실제 반영

### v2 (2026.02)
- 멀티턴 대화, 개정 이력 추적
- 관리자 페이지(업로드/개정/일괄치환/충돌분석)
- AI 형식 검사 (Groq)

### v1 (2026.01)
- 단일 턴 RAG 챗봇
- pgvector + sentence-transformers
- 정적 규정 목록

---

## 🤝 기여

이슈/PR 환영합니다.

## 📜 라이선스

학내 사용 + 공모전 제출용. 상업적 이용 금지.

---

**2026 한성대학교 AX 프론티어 공모전**