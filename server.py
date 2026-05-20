import os
import jwt
import difflib
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import psycopg2
from sentence_transformers import SentenceTransformer
from groq import Groq
from routers.teacher import router as teacher_router, set_ai_client
import re as _re
import json as _json
from pathlib import Path as _Path
from collections import defaultdict as _defaultdict
import secrets as _secrets

# ── 환경 변수 ─────────────────────────────────────────────────────
GROQ_KEY = os.getenv("GROQ_API_KEY")
DB_URL   = os.getenv("DATABASE_URL")

_raw_key   = os.getenv("SECRET_KEY", "")
SECRET_KEY = _raw_key if len(_raw_key) >= 32 else _secrets.token_hex(32)
if len(_raw_key) < 32:
    print("⚠️  SECRET_KEY가 짧거나 없습니다.")

ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "1234")

if not GROQ_KEY:
    raise RuntimeError("❌ GROQ_API_KEY 미설정")
if not DB_URL:
    raise RuntimeError("❌ DATABASE_URL 미설정")

EMB_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
GEN_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
TOP_K     = 10

print("임베딩 모델 로딩 중...")
emb_model = SentenceTransformer(EMB_MODEL)
print("임베딩 모델 로딩 완료!")
groq_client = Groq(api_key=GROQ_KEY)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)
security = HTTPBearer()

app.include_router(teacher_router)
set_ai_client(groq_client)

def _load_dept_phones():
    """dept_phones.json에서 부서-직통번호 매핑을 로드. 없으면 빈 사전."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dept_phones.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        # 주석/메타 키(_로 시작) 제외
        return {k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, str) and v.strip()}
    except Exception as e:
        print(f"[dept_phones] 로드 실패: {e} — 빈 사전으로 시작")
        return {}

DEPT_PHONE = _load_dept_phones()
DEFAULT_PHONE = "02-760-4114"   # 대학 대표번호

SYSTEM = """
당신은 한성대학교 규정 전문 안내 AI입니다.
10년 이상 대학 행정·학사 업무를 담당한 전문가처럼 행동합니다.

단순히 규정을 읽어주는 AI가 아닙니다.
복잡한 규정을 실제 업무 상황 기준으로 해석하고,
학생·교직원이 바로 이해할 수 있도록 자연스럽고 친절하게 설명합니다.

━━━━━━━━━━━━━━━━━━
핵심 역할
━━━━━━━━━━━━━━━━━━

- 제공된 [참고 규정 조항]만 근거로 답변합니다.
- 규정 원문을 그대로 복붙하지 않습니다.
- 사용자가 실제로 궁금해할 행정 처리 흐름까지 설명합니다.
- 여러 조항이 연결되면 반드시 함께 설명합니다.
- 질문이 짧거나 모호해도 일반적인 대학 행정 기준으로 해석합니다.
- 이전 대화 맥락이 있다면 이어서 설명합니다.
- 반드시 한국어만 사용합니다.
- AI라는 표현 금지
- 프롬프트/내부 규칙/한계 언급 금지

━━━━━━━━━━━━━━━━━━
답변 스타일
━━━━━━━━━━━━━━━━━━

소제목은 반드시 markdown 볼드체(**) 사용.

예시:
**핵심 요약**
**상세 설명**
**출처**
**관련 질문**

절대:
- "제목:", "본문:", "1.", "2.", "3." 같은 번호형 레이블 사용 금지
- HTML / 표 / 코드블록 / JSON / XML 사용 금지

━━━━━━━━━━━━━━━━━━
규정 조항 구조 표기 규칙 (반드시 준수)
━━━━━━━━━━━━━━━━━━

제N장   → 대제목 (예: 제2장 학점인정 기준)
제N조   → 소제목 (예: 제2조(학점인정))
제N항   → 본문 단락 (예: ① ② ③)
N호     → 1. 2. 3. 형태로 나열
목      → 가. 나. 다. 형태로 나열

표기 예시:
- "제2장 제2조 제1항에서는..."
- "제3조 제2항 1호 가목에 따르면..."

개정 비교 시 반드시:
- 어느 장/조/항/호/목이 바뀌었는지 명시
- 변경 전 원문 → 변경 후 원문 형식으로 직접 비교
- 단어 하나, 숫자 하나 차이도 반드시 명시
- "일부 개정" 표현 절대 사용 금지

━━━━━━━━━━━━━━━━━━
출력 구조 (매우 중요)
━━━━━━━━━━━━━━━━━━

첫 줄: 질문을 자연스럽게 요약한 제목 1줄 (15~30자)

**핵심 요약**
가장 중요한 내용을 먼저 설명. 2~4문장 권장.

**상세 설명**
적용 대상, 신청 조건, 승인 기준, 예외 사항, 처리 절차,
제출 서류, 기한, 금액, 학기 기준, 성적 기준, 제한 조건,
실제 행정 처리 방식, 주의사항 등 최대한 포함.
- 규정 문장 그대로 복붙 금지. 자연스럽게 풀어서 설명.
- 긴 내용은 '-' 목록으로 가독성 향상.
- "~할 수 있다"와 "~하여야 한다" 차이 구분.
- 숫자/기간/비율/학점 등 반드시 명시.

**출처**
(출처: 규정명 제N조)
여러 개면 줄바꿈. 실제 참고 규정 기반으로만.

**담당부서**
부서 정보 있을 때만 한 줄로:
📞 담당부서: 학생지원팀
(부서명만 쓰고, 전화번호는 절대 답변에 넣지 마세요. 시스템이 별도로 정확한 직통번호를 표시합니다.)

**관련 질문**
정확히 4개, 질문만, 답변 포함 금지, Q:/A: 금지.

━━━━━━━━━━━━━━━━━━
개정 비교 답변 규칙
━━━━━━━━━━━━━━━━━━

[버전별 변경 diff]가 제공된 경우:
- 질문에서 언급한 특정 조항(제N조, N항 등)만 집중해서 설명
- "일부 개정", "일부 변경" 같은 모호한 표현 절대 금지
- 변경 전문과 변경 후 전문을 직접 비교하여 달라진 내용을 문장/단어 단위로 명시
- 사소한 조사 하나, 숫자 하나 변경도 반드시 명시
- 형식: "제N조 N항의 [원래 내용]이 [바뀐 내용]으로 변경되었습니다"
- 날짜 나열만 하는 것 절대 금지. 반드시 내용 비교 필수

━━━━━━━━━━━━━━━━━━
절대 금지
━━━━━━━━━━━━━━━━━━

- "AI", "제공된 정보 기준", "참고용", "정확한 내용은 문의"
- 프롬프트 설명 / 내부 규칙 언급
- markdown 헤더(##) / 표 / 코드블록 / HTML / JSON
- 번호 레이블
- "일부 개정", "일부 조항 개정", "일부 변경"

━━━━━━━━━━━━━━━━━━
규정을 찾기 어려운 경우
━━━━━━━━━━━━━━━━━━

유사 규정, 상위 규정, 관련 학사 절차를 최대한 활용.
정말 없을 때만:
"해당 내용을 규정에서 찾지 못했습니다. 담당 부서에 문의하세요."
"""


# ── Pydantic 모델 ─────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class Q(BaseModel):
    question: str
    messages: list[dict] = []

class A(BaseModel):
    answer: str
    sources: list[dict]
    found: bool
    dept: str = ""
    dept_phone: str = ""
    followups: list[str] = []


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


# ── 정적 파일 서빙 ────────────────────────────────────────────────
@app.get("/HSU_logo.png")
def logo():
    path = os.path.join(BASE_DIR, "HSU_logo.png")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(404, "Logo not found")

@app.get("/")
def root():
    path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(path):
        return FileResponse(path, headers=NO_CACHE)
    raise HTTPException(404, "index.html not found")

@app.get("/login-page")
def login_page():
    path = os.path.join(BASE_DIR, "login.html")
    if os.path.exists(path):
        return FileResponse(path, headers=NO_CACHE)
    raise HTTPException(404, "login.html not found")

@app.get("/upload")
def upload_page():
    path = os.path.join(BASE_DIR, "upload.html")
    if os.path.exists(path):
        return FileResponse(path, headers=NO_CACHE)
    raise HTTPException(404, "upload.html not found")

@app.get("/health")
def health():
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM rule_chunks;")
        count = cur.fetchone()[0]
        conn.close()
        return {"ok": True, "chunks": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── 로그인 ────────────────────────────────────────────────────────
@app.post("/login")
def login(data: LoginRequest):
    if data.username != ADMIN_ID or data.password != ADMIN_PW:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    token = jwt.encode(
        {"sub": data.username, "exp": datetime.utcnow() + timedelta(hours=12)},
        SECRET_KEY, algorithm="HS256"
    )
    return {"success": True, "token": token}


# ── JWT 검증 ──────────────────────────────────────────────────────
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다.")
    except Exception:
        raise HTTPException(status_code=401, detail="인증에 실패했습니다.")


# ── 텍스트 추출 헬퍼 ──────────────────────────────────────────────
def _extract_text(file: UploadFile) -> str:
    import io
    file.file.seek(0)
    data  = file.file.read()
    fname = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()

    if fname.endswith(".pdf") or "pdf" in ctype:
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(io.BytesIO(data))
            if text and text.strip():
                return text.strip()
        except Exception:
            pass
        raise HTTPException(400, "PDF 텍스트 추출 실패")

    if fname.endswith(".docx") or "wordprocessingml" in ctype:
        from docx import Document as DocxDoc
        doc = DocxDoc(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if fname.endswith(".hwpx"):
        import zipfile
        texts = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                section_files = sorted([f for f in z.namelist()
                    if _re.match(r'Contents/[Ss]ection\d+\.xml', f)])
                if not section_files:
                    section_files = [f for f in z.namelist()
                        if f.endswith('.xml') and 'section' in f.lower()]
                from bs4 import BeautifulSoup as _BS
                for sf in section_files:
                    try:    soup = _BS(z.read(sf), "xml")
                    except: soup = _BS(z.read(sf), "html.parser")
                    for tag in soup.find_all(_re.compile(r'(?:hp:)?t$')):
                        if tag.get_text().strip():
                            texts.append(tag.get_text())
        except Exception as e:
            raise HTTPException(400, f"HWPX 추출 실패: {e}")
        return "\n".join(texts)

    if fname.endswith(".hwp"):
        import tempfile, subprocess, sys, os as _os
        tmp = _os.path.join(tempfile.gettempdir(), f"hsu_hwp_{_os.getpid()}.hwp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            scripts_dir = _os.path.join(_os.path.dirname(sys.executable), "Scripts")
            for cmd in [
                [_os.path.join(scripts_dir, "hwp5txt.exe"), tmp],
                ["hwp5txt", tmp],
                [sys.executable, "-m", "hwp5.hwp5txt", tmp],
            ]:
                try:
                    result = subprocess.run(cmd, capture_output=True, timeout=60,
                                            encoding="utf-8", errors="replace")
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip()
                except (FileNotFoundError, OSError):
                    continue
            raise HTTPException(400, "HWP 추출 실패.")
        finally:
            try: _os.unlink(tmp)
            except: pass

    if fname.endswith(".json"):
        try:
            items = _json.loads(data.decode("utf-8"))
            if isinstance(items, list):
                parts = []
                for item in items:
                    if isinstance(item, dict):
                        parts.append(" ".join(str(v) for v in item.values() if v))
                return "\n".join(parts)
            return _json.dumps(items, ensure_ascii=False)
        except Exception as e:
            raise HTTPException(400, f"JSON 파싱 실패: {e}")

    for enc in ["utf-8", "cp949", "euc-kr"]:
        try: return data.decode(enc).strip()
        except: continue
    return data.decode("utf-8", errors="ignore").strip()


def _chunk_text(text: str, max_len: int = 400) -> list[str]:
    paragraphs = [p.strip() for p in _re.split(r'\n{2,}', text) if p.strip()]
    chunks = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) < max_len:
            buf = (buf + "\n" + para).strip() if buf else para
        else:
            if buf: chunks.append(buf)
            if len(para) > max_len:
                sentences = _re.split(r'(?<=[.!?])\s+', para)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) < max_len:
                        buf = (buf + " " + s).strip() if buf else s
                    else:
                        if buf: chunks.append(buf)
                        buf = s
            else:
                buf = para
    if buf: chunks.append(buf)
    return [c for c in chunks if len(c) >= 20]


def _extract_article_title(chunk: str, idx: int) -> str:
    m = _re.search(r'(제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]{1,30}\))?)', chunk)
    if m:
        return m.group(1).strip()[:60]
    first = chunk.split('\n')[0].strip()
    if 3 < len(first) <= 50:
        return first
    return f"청크 {idx + 1}"


# ── 규정 파일 업로드 ──────────────────────────────────────────────
@app.post("/upload-regulation")
async def upload_regulation(file: UploadFile = File(...), payload: dict = Depends(verify_token)):
    filename  = file.filename or "unknown"
    upload_tag = f"upload://{filename}"

    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM rule_chunks WHERE url = %s", (upload_tag,))
        if cur.fetchone()[0] > 0:
            conn.close()
            raise HTTPException(409, f'"{filename}"은(는) 이미 등록된 규정입니다.')
        conn.close()
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, f"DB 확인 실패: {e}")

    try:    text = _extract_text(file)
    except HTTPException: raise
    except Exception as e: raise HTTPException(400, f"파일 읽기 실패: {e}")

    if not text or len(text.strip()) < 10:
        raise HTTPException(400, "텍스트 추출 불가")

    chunks = _chunk_text(text)
    if not chunks: raise HTTPException(400, "청크 분할 실패")

    try:    embeddings = emb_model.encode(chunks, normalize_embeddings=True).tolist()
    except Exception as e: raise HTTPException(500, f"임베딩 실패: {e}")

    CHAP_MAP_UP = {"1":"학교법인","2":"학칙","3":"학사행정","4":"부속기관",
                   "5":"부설기관","6":"위원회","7":"산학협력단","8":"학생군사교육단"}
    try:
        clf = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role":"user","content":f"""한성대학교 규정 체계에서 다음 문서가 속하는 편 번호(1~8)만 답하세요.
1편:학교법인 2편:학칙 3편:학사행정 4편:부속기관
5편:부설기관 6편:위원회 7편:산학협력단 8편:학생군사교육단
규정명: {filename}
내용: {text[:300]}
숫자 하나만 답하세요:"""}],
            max_tokens=3,
        )
        raw_clf  = clf.choices[0].message.content.strip()
        m_clf    = _re.search(r'[1-8]', raw_clf)
        chap_num = m_clf.group(0) if m_clf else "3"
    except: chap_num = "3"

    dept_tag   = f"업로드:{chap_num}"
    upload_tag = f"upload://{filename}"
    inserted   = 0
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        import time as _time
        base_id = int(_time.time() * 1000)
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur.execute("""
                INSERT INTO rule_chunks (id,rule_title,article,department,url,content,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s::vector)
            """, (str(base_id+i), filename, _extract_article_title(chunk,i),
                  dept_tag, upload_tag, chunk, str(emb)))
            inserted += 1
        conn.commit(); conn.close()
    except Exception as e: raise HTTPException(500, f"DB 저장 실패: {e}")

    os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)
    try:
        file.file.seek(0)
        with open(os.path.join(BASE_DIR, "uploads", filename), "wb") as f:
            f.write(file.file.read())
    except: pass

    return {"success": True, "filename": filename, "chunks": inserted}


# ── 업로드 규정 목록 / 삭제 ───────────────────────────────────────
@app.get("/uploaded-rules")
def list_uploaded_rules(payload: dict = Depends(verify_token)):
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("""
            SELECT url, COUNT(*) as cnt, MIN(id) as first_id
            FROM rule_chunks WHERE url LIKE 'upload://%'
            GROUP BY url ORDER BY first_id DESC
        """)
        rows = cur.fetchall(); conn.close()
    except Exception as e: raise HTTPException(500, f"DB 오류: {e}")
    return {"rules": [{"filename": r[0].replace("upload://",""), "chunks": r[1], "tag": r[0]} for r in rows]}

@app.delete("/uploaded-rules/{filename:path}")
def delete_uploaded_rule(filename: str, payload: dict = Depends(verify_token)):
    tag = f"upload://{filename}"
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("DELETE FROM rule_chunks WHERE url = %s", (tag,))
        deleted = cur.rowcount; conn.commit(); conn.close()
    except Exception as e: raise HTTPException(500, f"DB 삭제 실패: {e}")
    if deleted == 0: raise HTTPException(404, "해당 규정을 찾을 수 없습니다.")
    local = os.path.join(BASE_DIR, "uploads", filename)
    if os.path.exists(local): os.remove(local)
    return {"success": True, "filename": filename, "deleted_chunks": deleted}


# ── 날짜 파싱 헬퍼 ────────────────────────────────────────────────
def _parse_article_date(article: str, content: str = "", url: str = "") -> tuple[str, str]:
    """
    article 필드에서 날짜 추출 → (art_name, date_str)
    우선순위:
      1) article 끝 (YYYY-MM-DD)
      2) article 끝 (YYYY.MM.DD.)
      3) content 안 (2021.02.12.) 형태 — 규정 본문에 박힌 개정일
      4) URL SEQ_HISTORY fallback
    """
    # 1) YYYY-MM-DD
    m = _re.search(r'\((\d{4}-\d{2}-\d{2})\)$', article)
    if m:
        return article[:m.start()].strip(), m.group(1)

    # 2) YYYY.MM.DD.
    m = _re.search(r'\((\d{4}\.\d{2}\.\d{2})\.?\)$', article)
    if m:
        return article[:m.start()].strip(), m.group(1).replace('.', '-')

    art_name = _re.sub(r'\(\s*\)$', '', article).strip()

    # 3) content 안 개정/제정 날짜 — (2021.02.12.) 패턴
    if content:
        # "개정" 또는 "제정" 바로 뒤 날짜 우선
        mc = _re.search(r'(?:개정|제정|시행)[^\d(]*\((\d{4}[.\-]\d{2}[.\-]\d{2})\.?\)', content)
        if not mc:
            # 괄호 안 날짜 아무거나
            mc = _re.search(r'\((\d{4}[.\-]\d{2}[.\-]\d{2})\.?\)', content)
        if mc:
            raw = mc.group(1).replace('.', '-')
            # YYYY-MM-DD 형식 유효성 체크
            if _re.match(r'\d{4}-\d{2}-\d{2}', raw):
                return art_name, raw

    # 4) URL SEQ_HISTORY fallback
    hist_m = _re.search(r'SEQ_HISTORY=(\d+)', url or '')
    date_str = f"v{hist_m.group(1).zfill(6)}" if hist_m else "날짜미상"
    return art_name, date_str


# ── 버전 diff 생성 ────────────────────────────────────────────────
def get_revision_history(rule_title: str) -> str:
    """개정이력 청크 직접 조회 — 날짜 목록 반환"""
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        # 1) 개정이력 전용 청크
        cur.execute("""
            SELECT content FROM rule_chunks
            WHERE rule_title = %s AND article = '개정이력'
            LIMIT 1
        """, (rule_title,))
        row = cur.fetchone()
        if row:
            conn.close()
            return row[0]

        # 2) 없으면 article에서 날짜 수집해서 직접 만들기
        cur.execute("""
            SELECT DISTINCT article, url FROM rule_chunks
            WHERE rule_title = %s AND article != '개정이력'
            ORDER BY article
        """, (rule_title,))
        rows = cur.fetchall(); conn.close()

        dates = set()
        for article, url in rows:
            _, date_str = _parse_article_date(article, "", url)
            if _re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                dates.add(date_str)

        if not dates:
            return ""

        sorted_dates = sorted(dates, reverse=True)
        lines = [f"  - {d}" for d in sorted_dates]
        return f"[{rule_title}] 개정 이력\n총 {len(sorted_dates)}회\n" + "\n".join(lines)

    except Exception:
        return ""

def get_version_diff(rule_title: str, question: str = "") -> str:
    """
    버전 간 글자 단위 diff를 생성.
    1차: hansung_rules_history.json 의 versions 배열에서 직접 비교 (가장 정확).
    2차: 위가 실패하면 DB의 rule_chunks 에서 시도 (백업).
    """
    # ── 1차: JSON 원본에서 비교 ──
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "hansung_rules_history.json"), encoding="utf-8") as f:
            history = _json.load(f)
        reg = next((r for r in history if r.get("title", "").strip() == rule_title.strip()), None)
        if reg:
            versions = reg.get("versions", [])
            # 버전 식별자: revision_date + seq_history (날짜만 같으면 hist로 보조 정렬)
            #             content가 의미 있는(>30자) 버전만 사용
            usable = [v for v in versions if len((v.get("content") or "")) > 30]
            if len(usable) >= 2:
                # 최신순 정렬 (revision_date 내림차순, 같으면 seq_history 내림차순)
                usable.sort(key=lambda v: (v.get("revision_date", ""),
                                            v.get("seq_history", "")), reverse=True)
                # 질문에서 조 번호 추출
                art_keywords = _re.findall(r'제?\s*(\d+)\s*(?:장|조|항|절)', question)

                # 인접한 두 버전을 비교
                blocks = []
                for i in range(len(usable) - 1):
                    new_v = usable[i]
                    old_v = usable[i + 1]
                    new_c = (new_v.get("content") or "").strip()
                    old_c = (old_v.get("content") or "").strip()
                    if new_c == old_c:
                        continue

                    # 조 단위로 쪼개 비교 (제 N 조 패턴)
                    def split_articles(text):
                        # '\n제 N 조' 기준 분리
                        parts = _re.split(r'(?=^제\s*\d+\s*조)', text, flags=_re.M)
                        result = {}
                        for p in parts:
                            m = _re.match(r'^제\s*(\d+)\s*조', p)
                            if m: result[m.group(1)] = p.strip()
                        return result

                    new_arts = split_articles(new_c)
                    old_arts = split_articles(old_c)

                    # 비교 대상 조 선택: 질문에 조 번호 있으면 그것만, 없으면 변경된 모든 조
                    if art_keywords:
                        target_keys = [k for k in new_arts if k in art_keywords]
                    else:
                        target_keys = [k for k in new_arts
                                       if new_arts.get(k, "") != old_arts.get(k, "")]
                    target_keys = target_keys[:6]  # 너무 많으면 자름

                    new_date = new_v.get("revision_date") or "최신"
                    old_date = old_v.get("revision_date") or "이전"

                    for k in target_keys:
                        old_text = old_arts.get(k, "")
                        new_text = new_arts.get(k, "")
                        if not new_text:
                            continue
                        if old_text == new_text:
                            continue

                        # difflib 으로 글자 단위 diff
                        sm = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
                        changes = []
                        for tag, i1, i2, j1, j2 in sm.get_opcodes():
                            if tag == 'equal':
                                continue
                            o_seg = old_text[i1:i2].strip()
                            n_seg = new_text[j1:j2].strip()
                            if not o_seg and not n_seg:
                                continue
                            if tag == 'replace':
                                changes.append(f"  '{o_seg}' → '{n_seg}'")
                            elif tag == 'delete':
                                changes.append(f"  삭제: '{o_seg}'")
                            elif tag == 'insert':
                                changes.append(f"  추가: '{n_seg}'")
                        if not changes:
                            continue

                        block  = f"[제{k}조] {old_date} → {new_date}\n"
                        block += f"▼ 변경 전:\n{old_text[:600]}\n\n"
                        block += f"▲ 변경 후:\n{new_text[:600]}\n\n"
                        block += "변경 부분:\n" + "\n".join(changes[:20])
                        blocks.append(block)

                    if len(blocks) >= 8:
                        break

                if blocks:
                    return "\n\n".join(blocks[:10])
    except Exception as e:
        print(f"[get_version_diff JSON 비교 실패] {e}")

    # ── 2차: DB 청크 기반 (기존 로직) ──
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("""
            SELECT article, content, url FROM rule_chunks
            WHERE rule_title = %s AND article != '개정이력'
            ORDER BY article
        """, (rule_title,))
        rows = cur.fetchall(); conn.close()
    except Exception:
        return ""

    from collections import defaultdict
    art_versions = defaultdict(list)

    for article, content, url in rows:
        art_name, date_str = _parse_article_date(article, content, url)
        art_versions[art_name].append((date_str, content))

    art_keywords = _re.findall(r'제?\s*(\d+)\s*(?:장|조|항|절)', question)

    diff_results = []
    for art_name, ver_list in art_versions.items():
        if len(ver_list) < 2:
            continue
        if art_keywords:
            if not any(kw in art_name for kw in art_keywords):
                continue

        ver_list.sort(key=lambda x: x[0])

        for i in range(len(ver_list) - 1):
            date_old, content_old = ver_list[i]
            date_new, content_new = ver_list[i + 1]
            if content_old.strip() == content_new.strip():
                continue

            old_lines = content_old.strip().splitlines()
            new_lines = content_new.strip().splitlines()
            deleted = [l for l in old_lines if l.strip() and l.strip() not in {n.strip() for n in new_lines}]
            added   = [l for l in new_lines if l.strip() and l.strip() not in {o.strip() for o in old_lines}]

            block  = f"[{art_name}] {date_old} → {date_new} 변경\n"
            block += f"▼ 변경 전 전문:\n{content_old.strip()}\n\n"
            block += f"▲ 변경 후 전문:\n{content_new.strip()}\n\n"
            if deleted:
                block += "❌ 삭제된 내용:\n" + "\n".join(f"  - {l}" for l in deleted) + "\n"
            if added:
                block += "✅ 추가된 내용:\n" + "\n".join(f"  + {l}" for l in added) + "\n"
            diff_results.append(block)

    return "\n\n".join(diff_results[:10]) if diff_results else ""


# ── /diff 엔드포인트 (프론트 버전 비교 모달용) ────────────────────
@app.post("/diff")
def get_diff(req: Q):
    title = req.question.strip()
    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("SELECT DISTINCT rule_title FROM rule_chunks WHERE rule_title ILIKE %s LIMIT 1", (f"%{title}%",))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "규정을 찾을 수 없습니다.")
        matched = row[0]
        cur.execute("""
            SELECT article, content FROM rule_chunks
            WHERE rule_title = %s AND article != '개정이력' ORDER BY article
        """, (matched,))
        rows = cur.fetchall(); conn.close()
    except HTTPException: raise
    except Exception as e: raise HTTPException(500, str(e))

    from collections import defaultdict
    versions = defaultdict(dict)
    for article, content in rows:
        art_name, date_str = _parse_article_date(article, content)
        versions[date_str][art_name] = content

    sorted_dates = sorted(
        versions.keys(),
        key=lambda d: (0, d) if _re.match(r'\d{4}-\d{2}-\d{2}', d) else (1, d)
    )
    all_articles = sorted({a for v in versions.values() for a in v})

    pairs = []
    for i in range(len(sorted_dates) - 1):
        od, nd = sorted_dates[i], sorted_dates[i + 1]
        articles = []
        for art in all_articles:
            oc = versions[od].get(art, "")
            nc = versions[nd].get(art, "")
            if oc != nc:
                articles.append({"name": art, "old": oc, "new": nc})
        if articles:
            pairs.append({"from_date": od, "to_date": nd, "articles": articles})

    return {"title": matched, "pairs": pairs, "dates": sorted_dates}


# ── 규정 질의 ─────────────────────────────────────────────────────
@app.post("/query", response_model=A)
def query(req: Q):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "Empty question")

    try:
        expand_resp = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": f"""다음 질문에서 한국 대학 규정 검색에 쓸 핵심 키워드를 추출하세요.
동의어, 약어, 관련 법령 용어도 포함하세요. 쉼표로 구분해서 단어만 나열하세요.
질문: {q}
키워드:"""}],
            max_tokens=80,
        )
        extra_keywords = [k.strip() for k in expand_resp.choices[0].message.content.split(',') if k.strip()]
    except:
        extra_keywords = []

    search_text = q + ' ' + ' '.join(extra_keywords)

    try:
        qemb = emb_model.encode(search_text, normalize_embeddings=True).tolist()
    except Exception as e:
        raise HTTPException(500, f"Embedding error: {e}")

    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("""
            SELECT id, rule_title, article, department, url, content,
                   1 - (embedding <=> %s::vector) AS score
            FROM rule_chunks ORDER BY embedding <=> %s::vector LIMIT %s;
        """, (qemb, qemb, TOP_K))
        rows = list(cur.fetchall())

        raw_keywords = [w for w in (q + ' ' + ' '.join(extra_keywords)).replace("?","").split() if len(w) >= 3]
        keywords = list(raw_keywords)
        for w in raw_keywords:
            if len(w) >= 4:
                for i in range(0, len(w)-2, 2):
                    sub = w[i:i+3]
                    if sub not in keywords: keywords.append(sub)

        if keywords:
            existing_ids = {r[0] for r in rows}
            for kw in keywords:
                cur.execute("SELECT id,rule_title,article,department,url,content,0.85 AS score FROM rule_chunks WHERE article LIKE %s LIMIT %s", (f"%{kw}%", TOP_K))
                for r in cur.fetchall():
                    if r[0] not in existing_ids: rows.append(r); existing_ids.add(r[0])
                cur.execute("SELECT id,rule_title,article,department,url,content,0.7 AS score FROM rule_chunks WHERE content LIKE %s LIMIT %s", (f"%{kw}%", TOP_K))
                for r in cur.fetchall():
                    if r[0] not in existing_ids: rows.append(r); existing_ids.add(r[0])

        rows = sorted(rows, key=lambda x: x[6], reverse=True)[:TOP_K]
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")

    if not rows or rows[0][6] < 0.15:
        return A(answer="해당 내용을 규정에서 찾지 못했습니다. 담당 부서에 문의하세요.", sources=[], found=False)

    # ── 개정 비교 질문 감지 ───────────────────────────────────────
    DIFF_KEYWORDS = [
        "뭐가 바뀌", "무엇이 바뀌", "어떻게 바뀌",
        "개정 내용", "개정사항", "개정 정보", "개정 이력", "개정 비교",
        "개정일자", "개정날짜", "개정일", "언제 개정", "몇 번 개정",  # ← 추가
        "변경 내용", "변경사항", "달라진", "수정된", "차이",
        "언제 바뀌", "어떤 부분이", "뭐가 달라"
    ]
    is_diff_question = any(kw in q for kw in DIFF_KEYWORDS)

    diff_ctx = ""
    if is_diff_question and rows:
        from collections import Counter
        top_title = Counter(r[1] for r in rows).most_common(1)[0][0]

        # 내용 비교 질문인지 날짜 조회 질문인지 구분
        DATE_ONLY_KW = ["개정일자", "개정날짜", "개정일", "언제 개정", "몇 번 개정", "개정 이력", "개정 정보"]
        is_date_only = any(kw in q for kw in DATE_ONLY_KW)

        if is_date_only:
            hist = get_revision_history(top_title)
            if hist:
                diff_ctx = f"\n\n[개정 이력 데이터]\n{hist}"
        else:
            diff = get_version_diff(top_title, question=q)
            if diff:
                diff_ctx = f"\n\n[버전별 변경 diff]\n{diff}"

    ctx  = "\n\n".join([f"[조항 {i+1}] {r[1]} {r[2]}\n{r[5]}" for i, r in enumerate(rows)])
    ctx += diff_ctx

    # ── 멀티턴 히스토리 ───────────────────────────────────────────
    groq_msgs = [{"role": "system", "content": SYSTEM}]
    history = [m for m in req.messages if m.get("role") in ("user", "assistant")]
    prev = history[:-1][-6:] if len(history) > 1 else []
    for m in prev:
        groq_msgs.append({"role": m["role"], "content": m["content"]})
    groq_msgs.append({"role": "user", "content": f"[참고 규정 조항]\n{ctx}\n\n[질문]\n{q}"})

    try:
        resp = groq_client.chat.completions.create(
            model=GEN_MODEL, messages=groq_msgs, max_tokens=1024,
        )
        answer = resp.choices[0].message.content
    except Exception as e:
        raise HTTPException(500, f"Generation error: {e}")

    sources = [{"title": r[1], "article": r[2], "department": r[3], "url": r[4], "score": round(r[6], 3)} for r in rows]

    import re as _re2
    dept = ""; dept_phone = ""; followups = []

    dept_m = _re2.search(r'📞\s*담당부서\s*:\s*([^\n(]+)', answer)
    if dept_m:
        dept = dept_m.group(1).strip()
        for k, v in DEPT_PHONE.items():
            if k in dept: dept_phone = v; break
        if not dept_phone: dept_phone = DEFAULT_PHONE

    # 연관 질문 추출 — 다양한 형식 모두 매칭
    #   - **관련 질문** / 💡 관련 질문 / 관련 질문: / 연관 질문:
    fq_block = _re2.search(
        r'(?:\*\*\s*관련\s*질문\s*\*\*|💡[^\n]*|관련\s*질문\s*[:：]?|연관\s*질문\s*[:：]?)'
        r'\s*\n([\s\S]+?)(?=\n\n\*\*|\n\n[가-힣]|\Z)',
        answer
    )
    if fq_block:
        followups = []
        for line in fq_block.group(1).splitlines():
            stripped = line.strip()
            if not stripped: continue
            # 볼드(**) 마커, 번호/불릿/Q: 제거
            text = _re2.sub(r'\*\*', '', stripped)
            text = _re2.sub(r'^[-*•\d]+[.)]\s*', '', text).strip()
            text = _re2.sub(r'^Q:\s*', '', text, flags=_re2.IGNORECASE).strip()
            if _re2.match(r'^A:\s*', text, flags=_re2.IGNORECASE): continue
            # 너무 길거나 짧으면 제외 (질문 문장이 아닐 가능성)
            if len(text) < 5 or len(text) > 80: continue
            # 물음표 없으면 추가
            if not text.endswith('?') and not text.endswith('?'):
                text = text + '?'
            followups.append(text)
        followups = followups[:4]

    # AI가 4개 미만으로 줬으면 일반 fallback 으로 채우기
    _fallback_fu = [
        "관련 규정 원문은 어디서 볼 수 있나요?",
        "담당 부서에 직접 문의하려면 어떻게 하나요?",
        "비슷한 사례에는 어떤 게 있나요?",
        "예외 조항은 없나요?",
    ]
    for f in _fallback_fu:
        if len(followups) >= 4: break
        if f not in followups: followups.append(f)
    followups = followups[:4]

    clean_answer = _re2.sub(r'\n*📞[^\n]*담당부서[^\n]*', '', answer)
    # AI가 답변에 박은 '(...대표번호 ... 요청)' 같은 안내 문구 제거
    clean_answer = _re2.sub(r'\([^()\n]*대표번호[^()\n]*\)', '', clean_answer)
    clean_answer = _re2.sub(r'\(\s*\d{2,3}-\d{3,4}-\d{4}[^()\n]*\)', '', clean_answer)
    clean_answer = _re2.sub(r'\n*(?:\*\*\s*관련\s*질문\s*\*\*|💡[^\n]*|관련\s*질문\s*[:：]?|연관\s*질문\s*[:：]?)[\s\S]*', '', clean_answer)
    clean_answer = _re2.sub(r'(?m)^\s*\d+\s*[.\)]\s*(제목|본문|출처|담당부서|관련\s*질문)[^\n]*\n?', '', clean_answer)
    clean_answer = _re2.sub(r'(?m)^(제목|본문)\s*[:：]\s*', '', clean_answer)
    clean_answer = _re2.sub(r'(?m)^#{1,6}\s*(.+)$', r'\1', clean_answer)
    clean_answer = _re2.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', clean_answer)
    clean_answer = _re2.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', clean_answer)
    clean_answer = _re2.sub(r'(?m)^[-*_]{3,}\s*$', '', clean_answer)
    clean_answer = _re2.sub(r'(?m)^>\s*', '', clean_answer)
    clean_answer = _re2.sub(r'`+([^`]*)`+', r'\1', clean_answer)
    clean_answer = _re2.sub(r'\n{3,}', '\n\n', clean_answer).strip()

    return A(answer=clean_answer, sources=sources, found=True,
             dept=dept, dept_phone=dept_phone, followups=followups)


# ── 규정 목록 ─────────────────────────────────────────────────────
@app.get("/rules")
def get_rules():
    CHAP_MAP = {"1":"학교법인","2":"학칙","3":"학사행정","4":"부속기관",
                "5":"부설기관","6":"위원회","7":"산학협력단","8":"학생군사교육단"}
    chapters = _defaultdict(list)

    try:
        json_path = _Path(BASE_DIR) / "hansung_rules.json"
        if json_path.exists():
            rules = _json.loads(json_path.read_text(encoding="utf-8"))
            for r in rules:
                try:
                    title    = r.get("title", "제목 없음")
                    raw_code = r.get("rule_code", "")
                    if not raw_code:
                        code_m  = _re.search(r'(\d+)-(\d+)-(\d+)', r.get("content", ""))
                        raw_code = f"{code_m.group(1)}-{code_m.group(2)}-{code_m.group(3)}" if code_m else ""
                    chap_num  = raw_code.split("-")[0] if raw_code else "0"
                    chap_name = CHAP_MAP.get(chap_num, "기타")
                    chap_key  = f"제{chap_num}편 {chap_name}" if chap_num != "0" else "기타"
                    chapters[chap_key].append({
                        "seq": r.get("seq", 0), "code": raw_code,
                        "name": title, "dept": r.get("department", ""),
                        "url": r.get("url", ""), "uploaded": False
                    })
                except: continue
    except: pass

    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        cur.execute("SELECT DISTINCT rule_title,url,department FROM rule_chunks WHERE url LIKE 'upload://%' ORDER BY rule_title")
        for row in cur.fetchall():
            rule_title, url, department = row
            m_chap = _re.search(r'업로드:([1-8])', department or '')
            chap_num  = m_chap.group(1) if m_chap else "3"
            chap_name = CHAP_MAP.get(chap_num, "학사행정")
            chap_key  = f"제{chap_num}편 {chap_name}"
            chapters[chap_key].append({
                "seq": 9999, "code": f"{chap_num}-upload",
                "name": f"📎 {rule_title}", "dept": "업로드 규정",
                "url": "", "uploaded": True
            })
        conn.close()
    except: pass

    result = []
    for key in sorted(chapters.keys(), key=lambda x: (
        int(_re.search(r'제(\d+)편', x).group(1)) if _re.search(r'제(\d+)편', x) else
        (98 if x == "기타" else 99)
    )):
        result.append({"chapter": key, "rules": sorted(chapters[key], key=lambda x: x["code"])})
    return {"chapters": result, "total": sum(len(c["rules"]) for c in result)}


# ── 규정 키워드 검색 ──────────────────────────────────────────────
@app.post("/search-rules")
def search_rules(req: Q):
    q = req.question.strip()
    if not q: raise HTTPException(400, "Empty query")

    keywords = [w for w in q.split() if len(w) >= 2] or [q]

    try:
        conn = psycopg2.connect(DB_URL); cur = conn.cursor()
        rows = []; seen = set()
        for kw in keywords[:5]:
            cur.execute("SELECT rule_title,article,department,url,content FROM rule_chunks WHERE rule_title LIKE %s LIMIT 20", (f"%{kw}%",))
            for r in cur.fetchall():
                if (r[0],r[1]) not in seen: rows.append(r); seen.add((r[0],r[1]))
            cur.execute("SELECT rule_title,article,department,url,content FROM rule_chunks WHERE content LIKE %s OR article LIKE %s LIMIT 30", (f"%{kw}%",f"%{kw}%"))
            for r in cur.fetchall():
                if (r[0],r[1]) not in seen: rows.append(r); seen.add((r[0],r[1]))
        conn.close()
    except Exception as e: raise HTTPException(500, f"DB error: {e}")

    if not rows: return {"results": [], "query": q}

    from collections import defaultdict as _dd
    grouped = _dd(list)
    for r in rows:
        grouped[r[0]].append({"article":r[1],"department":r[2],"url":r[3] or "","snippet":r[4][:200].strip()})

    results = [{"title":t,"department":c[0]["department"],"url":c[0]["url"],"chunks":c[:3]}
               for t,c in grouped.items()]
    return {"results": results[:20], "query": q}




# ══════════════════════════════════════════════════════════════════
# 규정 개정 (Revision) — 기존 규정 내용 변경 + 되돌리기
# ══════════════════════════════════════════════════════════════════
RULES_JSON_PATH = os.path.join(BASE_DIR, "hansung_rules.json")
HISTORY_JSON_PATH = os.path.join(BASE_DIR, "hansung_rules_history.json")
REVISION_BACKUP_DIR = os.path.join(BASE_DIR, ".revision_backup")


def _load_rules_json() -> list:
    try:
        with open(RULES_JSON_PATH, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception as e:
        raise HTTPException(500, f"hansung_rules.json 로드 실패: {e}")


def _save_rules_json(data: list):
    try:
        with open(RULES_JSON_PATH, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(500, f"hansung_rules.json 저장 실패: {e}")


def _load_history_json() -> list:
    """hansung_rules_history.json 로드 (개정 기능 전용 — 버전 정보 포함)."""
    try:
        with open(HISTORY_JSON_PATH, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception as e:
        raise HTTPException(500, f"hansung_rules_history.json 로드 실패: {e}")


def _save_history_json(data: list):
    try:
        with open(HISTORY_JSON_PATH, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(500, f"hansung_rules_history.json 저장 실패: {e}")


def _get_latest_version(reg: dict) -> dict | None:
    """history JSON의 한 규정에서 최신 버전(is_latest=True)을 반환. 없으면 첫 버전."""
    versions = reg.get("versions", []) or []
    if not versions:
        return None
    for v in versions:
        if v.get("is_latest"):
            return v
    return versions[0]


def _get_latest_version_index(reg: dict) -> int:
    """최신 버전의 versions 배열 내 인덱스. 못 찾으면 0."""
    versions = reg.get("versions", []) or []
    for i, v in enumerate(versions):
        if v.get("is_latest"):
            return i
    return 0


# -- 개정 가능한 규정 목록 (검색용) --------------------------------
@app.get("/revisable-rules")
def revisable_rules(payload: dict = Depends(verify_token)):
    """hansung_rules_history.json 안의 규정 목록 — 개정 대상 선택용 (최신 버전 기준)"""
    history = _load_history_json()
    out = []
    for r in history:
        try:
            latest = _get_latest_version(r)
            if not latest:
                continue
            out.append({
                "seq":         r.get("seq", 0),
                "title":       r.get("title", "제목 없음"),
                "department":  r.get("department", ""),
                "chapter":     "",
                "code":        "",
                "revised_at":  latest.get("revision_date", ""),
                "content_len": len(latest.get("content", "") or ""),
            })
        except Exception:
            continue
    out.sort(key=lambda x: x["seq"])
    return {"rules": out, "total": len(out)}


# -- 특정 규정 현재 내용 조회 (최신 버전) --------------------------
@app.get("/revisable-rules/{seq}")
def revisable_rule_detail(seq: int, payload: dict = Depends(verify_token)):
    history = _load_history_json()
    for r in history:
        if int(r.get("seq", -1)) == seq:
            latest = _get_latest_version(r)
            if not latest:
                raise HTTPException(404, "최신 버전을 찾을 수 없습니다.")
            return {
                "seq":          r.get("seq"),
                "title":        r.get("title", ""),
                "department":   r.get("department", ""),
                "content":      latest.get("content", ""),
                "revised_at":   latest.get("revision_date", ""),
                "version_count": len(r.get("versions", [])),
            }
    raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")


def _reindex_rule_chunks(seq, title: str, dept: str, url: str, content: str) -> int:
    """DB에서 해당 seq의 본문 청크(개정이력/업로드 제외)를 새 content로 재생성"""
    chunks = _chunk_text(content)
    if not chunks:
        raise HTTPException(400, "개정 내용에서 청크를 만들 수 없습니다.")
    try:
        embeddings = emb_model.encode(chunks, normalize_embeddings=True).tolist()
    except Exception as e:
        raise HTTPException(500, f"임베딩 실패: {e}")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM rule_chunks
            WHERE seq = %s AND article != '개정이력'
              AND (url IS NULL OR url NOT LIKE 'upload://%%')
        """, (str(seq),))
        import time as _time
        base_id = int(_time.time() * 1000)
        inserted = 0
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur.execute("""
                INSERT INTO rule_chunks (id,rule_title,seq,article,department,url,content,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)
            """, (f"r{seq}_rev_{base_id+i}", title, str(seq),
                  _extract_article_title(chunk, i), dept, url, chunk, str(emb)))
            inserted += 1
        conn.commit()
        return inserted
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, f"DB 재색인 실패: {e}")
    finally:
        conn.close()


# -- 규정 개정 (전체) ----------------------------------------------
@app.post("/revise-regulation")
async def revise_regulation(
    seq: int = Form(...),
    text: str = Form(None),
    file: UploadFile = File(None),
    payload: dict = Depends(verify_token),
):
    """
    기존 규정(seq)을 새 내용으로 개정한다.
    - file 또는 text 중 하나로 새 본문을 받는다.
    - history.json의 최신 버전 content 를 새 내용으로 덮어쓴다.
    - 그 규정에 '이 날짜에 바뀜' 한 줄만 revisions[] 에 기록한다.
    - 개정 전 상태를 .revision_backup/ 에 백업한다 (되돌리기용).
    - DB 본문 청크도 재색인한다.
    """
    new_content = ""
    if file is not None and (file.filename or ""):
        try:
            new_content = _extract_text(file)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"파일 읽기 실패: {e}")
    elif text and text.strip():
        new_content = text.strip()
    else:
        raise HTTPException(400, "개정할 내용(파일 또는 텍스트)이 필요합니다.")

    if not new_content or len(new_content.strip()) < 10:
        raise HTTPException(400, "개정 내용이 너무 짧습니다.")

    history = _load_history_json()
    target_idx = None
    for i, r in enumerate(history):
        if int(r.get("seq", -1)) == seq:
            target_idx = i
            break
    if target_idx is None:
        raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")

    target = history[target_idx]
    latest_idx = _get_latest_version_index(target)
    latest = target["versions"][latest_idx]

    title = target.get("title", "")
    dept = target.get("department", "")
    url = latest.get("url") or target.get("url_latest", "")
    today = datetime.now().strftime("%Y-%m-%d")

    # 백업
    os.makedirs(REVISION_BACKUP_DIR, exist_ok=True)
    backup_id = f"{seq}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT id,rule_title,seq,article,department,url,content
            FROM rule_chunks
            WHERE seq = %s AND article != '개정이력'
              AND (url IS NULL OR url NOT LIKE 'upload://%%')
        """, (str(seq),))
        db_rows = [
            {"id": c[0], "rule_title": c[1], "seq": c[2], "article": c[3],
             "department": c[4], "url": c[5], "content": c[6]}
            for c in cur.fetchall()
        ]
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"백업용 DB 조회 실패: {e}")

    backup = {
        "backup_id":     backup_id,
        "seq":           seq,
        "title":         title,
        "backed_up_at":  datetime.now().isoformat(timespec="seconds"),
        "kind":          "regulation_history",
        "history_item":  target,        # 개정 전 history 항목 통째로
        "db_chunks":     db_rows,
    }
    with open(os.path.join(REVISION_BACKUP_DIR, f"{backup_id}.json"),
              "w", encoding="utf-8") as f:
        _json.dump(backup, f, ensure_ascii=False, indent=2)

    # history.json 갱신 — 최신 버전 content 덮어쓰기 + 날짜 기록
    target["versions"][latest_idx]["content"] = new_content
    target["versions"][latest_idx]["revision_date"] = today

    revisions = target.get("revisions", [])
    revisions.append({
        "revised_at":       today,
        "prev_content_len": len(latest.get("content", "") or ""),
        "new_content_len":  len(new_content),
        "backup_id":        backup_id,
    })
    target["revisions"] = revisions
    history[target_idx] = target
    _save_history_json(history)

    # DB 재색인
    new_chunks = _reindex_rule_chunks(seq, title, dept, url, new_content)

    return {
        "success": True, "seq": seq, "title": title,
        "revised_at": today, "backup_id": backup_id,
        "new_chunks": new_chunks,
    }


# -- 되돌리기: 백업 목록 -------------------------------------------
@app.get("/revision-backups")
def revision_backups(payload: dict = Depends(verify_token)):
    """되돌릴 수 있는 개정 백업 목록 (최신순)"""
    if not os.path.isdir(REVISION_BACKUP_DIR):
        return {"backups": []}
    items = []
    for fn in os.listdir(REVISION_BACKUP_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(REVISION_BACKUP_DIR, fn), "r", encoding="utf-8") as f:
                b = _json.load(f)
            items.append({
                "backup_id":    b.get("backup_id"),
                "seq":          b.get("seq"),
                "title":        b.get("title"),
                "backed_up_at": b.get("backed_up_at"),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("backed_up_at") or "", reverse=True)
    return {"backups": items}


# -- 되돌리기 실행 -------------------------------------------------
def _restore_one(seq, json_item: dict, db_chunks: list, rules: list) -> bool:
    """규정 1개를 JSON + DB 모두 개정 전 상태로 복원. (JSON은 rules 리스트를 직접 수정)"""
    restored = False
    for i, r in enumerate(rules):
        if int(r.get("seq", -1)) == int(seq):
            rules[i] = json_item
            restored = True
            break
    if not restored:
        return False

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        cur.execute("""
            DELETE FROM rule_chunks
            WHERE seq = %s AND article != '개정이력'
              AND (url IS NULL OR url NOT LIKE 'upload://%%')
        """, (str(seq),))
        for c in db_chunks:
            emb = emb_model.encode([c["content"]],
                                   normalize_embeddings=True).tolist()[0]
            cur.execute("""
                INSERT INTO rule_chunks (id,rule_title,seq,article,department,url,content,embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)
            """, (c["id"], c["rule_title"], c["seq"], c["article"],
                  c["department"], c["url"], c["content"], str(emb)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return True


@app.post("/revision-rollback")
def revision_rollback(backup_id: str = Form(...), payload: dict = Depends(verify_token)):
    """백업을 사용해 JSON + DB를 개정 전 상태로 되돌린다.
       단일/일괄 + rules.json 기반/history.json 기반 백업 모두 지원."""
    backup_path = os.path.join(REVISION_BACKUP_DIR, f"{backup_id}.json")
    if not os.path.exists(backup_path):
        raise HTTPException(404, "해당 백업을 찾을 수 없습니다.")

    with open(backup_path, "r", encoding="utf-8") as f:
        backup = _json.load(f)

    kind = backup.get("kind", "")

    try:
        # ── history.json 기반 백업 (전체개정 / 조 단위 개정) ──
        if kind in ("regulation_history", "article_history"):
            history = _load_history_json()
            seq = backup["seq"]
            saved_target = backup.get("history_item")
            if not saved_target:
                raise HTTPException(400, "백업에 history_item 이 없습니다.")
            # history 안에서 해당 seq 찾아서 통째로 교체
            replaced = False
            for i, r in enumerate(history):
                if int(r.get("seq", -1)) == int(seq):
                    history[i] = saved_target
                    replaced = True
                    break
            if not replaced:
                raise HTTPException(404, f"seq={seq} 규정이 현재 history.json에 없습니다.")
            _save_history_json(history)

            # DB도 백업 청크로 복원
            conn = psycopg2.connect(DB_URL); cur = conn.cursor()
            try:
                cur.execute("""
                    DELETE FROM rule_chunks
                    WHERE seq = %s AND article != '개정이력'
                      AND (url IS NULL OR url NOT LIKE 'upload://%%')
                """, (str(seq),))
                for c in backup.get("db_chunks", []):
                    emb = emb_model.encode([c["content"]],
                                           normalize_embeddings=True).tolist()[0]
                    cur.execute("""
                        INSERT INTO rule_chunks (id,rule_title,seq,article,department,url,content,embedding)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    """, (c["id"], c["rule_title"], c["seq"], c["article"],
                          c["department"], c["url"], c["content"], str(emb)))
                conn.commit()
            finally:
                conn.close()
            result = {"success": True, "backup_id": backup_id, "kind": kind,
                      "seq": seq, "restored_chunks": len(backup.get("db_chunks", []))}

        # ── 일괄 치환 (rules.json 기반) ──
        elif kind == "bulk_replace":
            rules = _load_rules_json()
            items = backup.get("items", [])
            restored_cnt = 0
            for it in items:
                ok = _restore_one(it["seq"], it["json_item"],
                                  it.get("db_chunks", []), rules)
                if ok:
                    restored_cnt += 1
            _save_rules_json(rules)
            result = {"success": True, "backup_id": backup_id,
                      "kind": "bulk_replace", "restored_rules": restored_cnt}

        # ── 옛 단일 규정 백업 (rules.json 기반) ──
        else:
            rules = _load_rules_json()
            ok = _restore_one(backup["seq"], backup["json_item"],
                              backup.get("db_chunks", []), rules)
            if not ok:
                raise HTTPException(404, f"seq={backup.get('seq')} 규정이 현재 JSON에 없습니다.")
            _save_rules_json(rules)
            result = {"success": True, "backup_id": backup_id,
                      "seq": backup["seq"],
                      "restored_chunks": len(backup.get("db_chunks", []))}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"되돌리기 실패: {e}")

    try:
        os.remove(backup_path)
    except Exception:
        pass

    return result




# ══════════════════════════════════════════════════════════════════
# 조(條) 단위 개정 — 규정 본문을 조 단위로 분할 / 특정 조만 개정
# ══════════════════════════════════════════════════════════════════
def _split_articles(content: str) -> list:
    """
    규정 본문을 조(條) 단위로 분할.
    줄 시작이 '제 N 조' 인 줄만 조 머리글로 인정 (본문 인용 '제2조' 제외).
    반환: [{index, head, body, start, end}]  (start/end = content 내 문자 오프셋)
    """
    head_re = _re.compile(r'^제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?')
    arts = []
    pos = 0
    cur = None
    for ln in content.split("\n"):
        line_len = len(ln) + 1  # +1 = '\n'
        s = ln.strip()
        if head_re.match(s):
            if cur is not None:
                cur["end"] = pos
                arts.append(cur)
            cur = {"head": s, "start": pos, "end": None}
        pos += line_len
    if cur is not None:
        cur["end"] = len(content)
        arts.append(cur)

    # 중복 조 번호에 [n/m] 라벨 부여
    num_re = _re.compile(r'^제\s*(\d+)\s*조(?:의\s*(\d+))?')
    from collections import Counter as _C
    keys = []
    for a in arts:
        m = num_re.match(a["head"])
        keys.append((m.group(1), m.group(2)) if m else (a["head"], None))
    total = _C(keys)
    seen = {}
    out = []
    for i, a in enumerate(arts):
        k = keys[i]
        body = content[a["start"]:a["end"]]
        dup_label = ""
        if total[k] > 1:
            seen[k] = seen.get(k, 0) + 1
            dup_label = f" [{seen[k]}/{total[k]}]"
        out.append({
            "index":     i,
            "head":      a["head"],
            "dup_label": dup_label,
            "start":     a["start"],
            "end":       a["end"],
            "body_len":  len(body.strip()),
        })
    return out


# -- 특정 규정의 조 목록 (최신 버전 기준) ---------------------------
@app.get("/rule-articles/{seq}")
def rule_articles(seq: int, payload: dict = Depends(verify_token)):
    history = _load_history_json()
    target = None
    for r in history:
        if int(r.get("seq", -1)) == seq:
            target = r
            break
    if target is None:
        raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")
    latest = _get_latest_version(target)
    if not latest:
        raise HTTPException(404, "최신 버전을 찾을 수 없습니다.")
    content = latest.get("content", "") or ""
    arts = _split_articles(content)
    return {
        "seq":      seq,
        "title":    target.get("title", ""),
        "articles": arts,
        "count":    len(arts),
    }


# -- 특정 조 1개의 현재 본문 (최신 버전 기준) -----------------------
@app.get("/rule-articles/{seq}/{index}")
def rule_article_detail(seq: int, index: int, payload: dict = Depends(verify_token)):
    history = _load_history_json()
    target = None
    for r in history:
        if int(r.get("seq", -1)) == seq:
            target = r
            break
    if target is None:
        raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")
    latest = _get_latest_version(target)
    if not latest:
        raise HTTPException(404, "최신 버전을 찾을 수 없습니다.")
    content = latest.get("content", "") or ""
    arts = _split_articles(content)
    if index < 0 or index >= len(arts):
        raise HTTPException(404, "해당 조를 찾을 수 없습니다.")
    a = arts[index]
    return {
        "seq":   seq,
        "index": index,
        "head":  a["head"] + a["dup_label"],
        "text":  content[a["start"]:a["end"]],
    }


# -- 조 단위 개정 --------------------------------------------------
@app.post("/revise-article")
async def revise_article(
    seq: int = Form(...),
    index: int = Form(...),
    text: str = Form(...),
    payload: dict = Depends(verify_token),
):
    """
    규정(seq) 안의 index번째 조항만 새 내용으로 교체한다 (history.json 최신 버전 기준).
    - 개정된 조 머리글 옆에 (개정 YYYY-MM-DD) 표시를 붙인다.
    - 개정 전 상태를 .revision_backup/ 에 백업한다.
    - DB는 해당 규정 본문 청크를 통째로 재색인한다.
    - revisions[] 에 '이 조가 이 날 바뀜' 한 줄 기록.
    """
    new_text = (text or "").strip()
    if len(new_text) < 5:
        raise HTTPException(400, "개정할 조항 내용이 너무 짧습니다.")

    history = _load_history_json()
    target_idx = None
    for i, r in enumerate(history):
        if int(r.get("seq", -1)) == seq:
            target_idx = i
            break
    if target_idx is None:
        raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")

    target = history[target_idx]
    latest_idx = _get_latest_version_index(target)
    latest = target["versions"][latest_idx]

    title = target.get("title", "")
    dept = target.get("department", "")
    url = latest.get("url") or target.get("url_latest", "")
    content = latest.get("content", "") or ""

    arts = _split_articles(content)
    if index < 0 or index >= len(arts):
        raise HTTPException(404, "해당 조를 찾을 수 없습니다.")
    a = arts[index]
    today = datetime.now().strftime("%Y-%m-%d")

    # 새 조항 본문에 (개정 YYYY-MM-DD) 표시 — 머리글 줄 끝에 부착
    nt_lines = new_text.split("\n")
    head_re = _re.compile(r'^(제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]*\))?)')
    if nt_lines and head_re.match(nt_lines[0].strip()):
        first = nt_lines[0].rstrip()
        # 기존 (개정 ...) 표시 있으면 제거 후 새로 부착
        first = _re.sub(r'\s*\(개정\s*\d{4}-\d{2}-\d{2}\)\s*$', '', first)
        nt_lines[0] = f"{first} (개정 {today})"
        new_article = "\n".join(nt_lines)
    else:
        # 머리글이 없으면 원래 머리글을 살려 붙임
        new_article = f"{a['head']} (개정 {today})\n{new_text}"

    new_content = content[:a["start"]] + new_article
    if not new_content.endswith("\n"):
        new_content += "\n"
    new_content += content[a["end"]:]

    # 백업 (history 항목 통째로 + DB 본문 청크)
    os.makedirs(REVISION_BACKUP_DIR, exist_ok=True)
    backup_id = f"{seq}_art{index}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("""
            SELECT id,rule_title,seq,article,department,url,content
            FROM rule_chunks
            WHERE seq = %s AND article != '개정이력'
              AND (url IS NULL OR url NOT LIKE 'upload://%%')
        """, (str(seq),))
        db_rows = [
            {"id": c[0], "rule_title": c[1], "seq": c[2], "article": c[3],
             "department": c[4], "url": c[5], "content": c[6]}
            for c in cur.fetchall()
        ]
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"백업용 DB 조회 실패: {e}")

    backup = {
        "backup_id":     backup_id,
        "seq":           seq,
        "title":         f"{title} — {a['head']}{a['dup_label']}",
        "backed_up_at":  datetime.now().isoformat(timespec="seconds"),
        "kind":          "article_history",
        "history_item":  target,
        "db_chunks":     db_rows,
    }
    with open(os.path.join(REVISION_BACKUP_DIR, f"{backup_id}.json"),
              "w", encoding="utf-8") as f:
        _json.dump(backup, f, ensure_ascii=False, indent=2)

    # history.json 갱신 — 최신 버전 content 만 덮어쓰기
    target["versions"][latest_idx]["content"] = new_content
    target["versions"][latest_idx]["revision_date"] = today

    # revisions[]에 '어떤 조가 언제 바뀌었는지' 기록 (나중에 '언제 바뀌었나' 질문에 답할 수 있도록)
    revisions = target.get("revisions", [])
    revisions.append({
        "kind":         "article",
        "article_head": a["head"] + a["dup_label"],
        "revised_at":   today,
        "backup_id":    backup_id,
    })
    target["revisions"] = revisions
    history[target_idx] = target
    _save_history_json(history)

    # DB 본문 청크 재색인
    new_chunks = _reindex_rule_chunks(seq, title, dept, url, new_content)

    return {
        "success": True, "seq": seq, "index": index,
        "article": a["head"] + a["dup_label"],
        "revised_at": today, "backup_id": backup_id,
        "new_chunks": new_chunks,
    }




# ══════════════════════════════════════════════════════════════════
# 조 단위 개정 — 파일 업로드 + AI 개정안 추출
# ══════════════════════════════════════════════════════════════════
@app.post("/extract-article-revision")
async def extract_article_revision(
    seq: int = Form(...),
    index: int = Form(...),
    file: UploadFile = File(...),
    payload: dict = Depends(verify_token),
):
    """
    개정 문서 파일을 받아:
      1) 파일에서 전체 텍스트를 추출한다 (원본 그대로 반환).
      2) AI가 그 문서에서 '대상 조항의 개정안' 부분을 찾아 추출한다.
    실제 개정은 하지 않는다. 프론트의 편집칸을 채우는 용도.
    """
    # 1) 대상 규정 / 조항 확인 (history.json 최신 버전 기준)
    history = _load_history_json()
    target = None
    for r in history:
        if int(r.get("seq", -1)) == seq:
            target = r
            break
    if target is None:
        raise HTTPException(404, f"seq={seq} 규정을 찾을 수 없습니다.")

    latest = _get_latest_version(target)
    if not latest:
        raise HTTPException(404, "최신 버전을 찾을 수 없습니다.")
    content = latest.get("content", "") or ""
    arts = _split_articles(content)
    if index < 0 or index >= len(arts):
        raise HTTPException(404, "해당 조를 찾을 수 없습니다.")
    a = arts[index]
    art_head = a["head"] + a["dup_label"]
    current_text = content[a["start"]:a["end"]].strip()

    # 2) 파일 텍스트 추출
    try:
        raw_text = _extract_text(file)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"파일 읽기 실패: {e}")

    if not raw_text or len(raw_text.strip()) < 10:
        raise HTTPException(400, "파일에서 텍스트를 추출하지 못했습니다.")

    raw_text = raw_text.strip()

    # 3) AI 개정안 추출
    #    문서가 길면 앞부분만 (모델 토큰 보호)
    doc_for_ai = raw_text[:6000]
    ai_text = ""
    ai_note = ""
    try:
        prompt = f"""너는 대학 규정 개정 문서를 분석하는 도우미다.

아래는 어떤 규정 개정 관련 문서에서 추출한 텍스트다. 이 문서에는 회의 안건 양식,
개정 사유, 현행규정과 개정(안)이 섞여 있을 수 있다.

[목표]
'{target.get("title","")}' 규정의 다음 조항에 해당하는 '개정(안)' 본문만 정확히 추출하라.

[대상 조항]
{art_head}

[현재 규정상의 해당 조항 원문 (참고용)]
{current_text[:800]}

[분석할 문서 텍스트]
{doc_for_ai}

[규칙]
- 문서에 '현행규정'과 '개정(안)'이 함께 있으면, 반드시 '개정(안)' 쪽 내용만 골라라.
- 대상 조항({art_head})에 해당하는 부분만 추출하고, 다른 조항은 포함하지 마라.
- 회의 양식, 개정 사유, 협의 여부 같은 행정 문구는 제외하라.
- 조 머리글(제 N 조 (제목))부터 그 조항 본문 끝까지 그대로 출력하라.
- 문서에서 해당 조항의 개정안을 찾을 수 없으면 정확히 'NOT_FOUND' 한 단어만 출력하라.
- 설명·머리말 없이 추출한 본문만 출력하라."""
        resp = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0,
        )
        ai_text = (resp.choices[0].message.content or "").strip()
        # 코드블록 마크다운 제거
        ai_text = _re.sub(r'^```[a-zA-Z]*\s*', '', ai_text)
        ai_text = _re.sub(r'\s*```$', '', ai_text).strip()

        if ai_text.upper().replace(" ", "") in ("NOT_FOUND", "NOTFOUND") or len(ai_text) < 5:
            ai_text = ""
            ai_note = "AI가 이 문서에서 해당 조항의 개정안을 찾지 못했습니다. 원본 텍스트를 보고 직접 입력하세요."
        else:
            ai_note = "AI가 추출한 개정안입니다. 반드시 원본과 대조해 확인·수정 후 개정하세요."
    except Exception as e:
        ai_text = ""
        ai_note = f"AI 추출에 실패했습니다({e}). 원본 텍스트를 보고 직접 입력하세요."

    return {
        "seq":          seq,
        "index":        index,
        "article_head": art_head,
        "ai_text":      ai_text,       # AI가 뽑은 개정안 (없으면 빈 문자열)
        "ai_note":      ai_note,       # 안내 문구
        "raw_text":     raw_text,      # 파일 원본 전체 텍스트
        "raw_truncated": len(raw_text) > 6000,
    }




# ══════════════════════════════════════════════════════════════════
# 단어 검색 / 일괄 치환 (Bulk word replace)
# ══════════════════════════════════════════════════════════════════

def _find_word_hits(content: str, word: str, ctx: int = 25) -> list:
    """content 안에서 word가 나오는 위치를 모두 찾아 앞뒤 문맥과 함께 반환"""
    hits = []
    if not word:
        return hits
    start = 0
    while True:
        idx = content.find(word, start)
        if idx == -1:
            break
        a = max(0, idx - ctx)
        b = min(len(content), idx + len(word) + ctx)
        hits.append({
            "pos":    idx,
            "before": content[a:idx],
            "match":  content[idx:idx+len(word)],
            "after":  content[idx+len(word):b],
        })
        start = idx + len(word)
    return hits


# -- 단어가 들어간 규정 검색 (챗봇/관리자 공용) ---------------------
class WordQ(BaseModel):
    word: str


@app.post("/word-search")
def word_search(req: WordQ):
    """본문에 특정 단어가 들어간 모든 규정을 찾는다. (인증 불필요 — 검색 전용)"""
    word = (req.word or "").strip()
    if not word:
        raise HTTPException(400, "검색할 단어를 입력하세요.")

    rules = _load_rules_json()
    results = []
    total_hits = 0
    for r in rules:
        content = r.get("content", "") or ""
        cnt = content.count(word)
        if cnt > 0:
            total_hits += cnt
            sample = _find_word_hits(content, word)[:3]
            results.append({
                "seq":     r.get("seq"),
                "title":   r.get("title", ""),
                "department": r.get("department", ""),
                "count":   cnt,
                "samples": sample,
            })
    results.sort(key=lambda x: -x["count"])
    return {"word": word, "rule_count": len(results),
            "total_hits": total_hits, "results": results}


# -- 일괄 치환 미리보기 (관리자) -----------------------------------
class ReplacePreviewQ(BaseModel):
    old_word: str
    new_word: str


@app.post("/bulk-replace/preview")
def bulk_replace_preview(req: ReplacePreviewQ, payload: dict = Depends(verify_token)):
    """old_word → new_word 치환 시 어떤 규정의 어디가 바뀌는지 미리 보여준다."""
    old = (req.old_word or "").strip()
    new = req.new_word if req.new_word is not None else ""
    if not old:
        raise HTTPException(400, "바꿀 단어(old_word)를 입력하세요.")
    if old == new:
        raise HTTPException(400, "바꿀 단어와 새 단어가 같습니다.")

    rules = _load_rules_json()
    results = []
    total_hits = 0
    for r in rules:
        content = r.get("content", "") or ""
        hits = _find_word_hits(content, old)
        if hits:
            total_hits += len(hits)
            results.append({
                "seq":   r.get("seq"),
                "title": r.get("title", ""),
                "department": r.get("department", ""),
                "count": len(hits),
                "hits":  hits[:20],   # 미리보기는 규정당 최대 20곳
            })
    results.sort(key=lambda x: -x["count"])
    return {
        "old_word": old, "new_word": new,
        "rule_count": len(results), "total_hits": total_hits,
        "results": results,
    }


# -- 일괄 치환 실행 (관리자) ---------------------------------------
class BulkReplaceQ(BaseModel):
    old_word: str
    new_word: str
    seqs: list[int]          # 실제로 치환할 규정 seq 목록 (미리보기에서 체크한 것)


@app.post("/bulk-replace/apply")
def bulk_replace_apply(req: BulkReplaceQ, payload: dict = Depends(verify_token)):
    """
    선택된 규정들에서 old_word → new_word 일괄 치환.
    - 전체 작업을 하나의 batch 백업으로 저장 (한 번에 되돌리기 가능)
    - 각 규정 JSON content 갱신 + DB 본문 청크 재색인
    """
    old = (req.old_word or "").strip()
    new = req.new_word if req.new_word is not None else ""
    if not old:
        raise HTTPException(400, "바꿀 단어를 입력하세요.")
    if old == new:
        raise HTTPException(400, "바꿀 단어와 새 단어가 같습니다.")
    if not req.seqs:
        raise HTTPException(400, "치환할 규정을 1개 이상 선택하세요.")

    rules = _load_rules_json()
    seq_set = set(req.seqs)
    today = datetime.now().strftime("%Y-%m-%d")

    # 백업 준비
    os.makedirs(REVISION_BACKUP_DIR, exist_ok=True)
    batch_id = f"bulk_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_items = []   # 규정별 개정 전 스냅샷

    changed = []
    for idx, r in enumerate(rules):
        seq = r.get("seq")
        if seq not in seq_set:
            continue
        content = r.get("content", "") or ""
        cnt = content.count(old)
        if cnt == 0:
            continue

        title = r.get("title", "")
        dept  = r.get("department", "")
        url   = r.get("url", "")

        # 개정 전 DB 청크 백업
        try:
            conn = psycopg2.connect(DB_URL); cur = conn.cursor()
            cur.execute("""
                SELECT id,rule_title,seq,article,department,url,content
                FROM rule_chunks
                WHERE seq = %s AND article != '개정이력'
                  AND (url IS NULL OR url NOT LIKE 'upload://%%')
            """, (str(seq),))
            db_rows = [
                {"id": c[0], "rule_title": c[1], "seq": c[2], "article": c[3],
                 "department": c[4], "url": c[5], "content": c[6]}
                for c in cur.fetchall()
            ]
            conn.close()
        except Exception as e:
            raise HTTPException(500, f"백업용 DB 조회 실패(seq {seq}): {e}")

        backup_items.append({
            "seq": seq, "title": title,
            "json_item": dict(r),       # 개정 전 JSON 원본
            "db_chunks": db_rows,
        })

        # 치환
        new_content = content.replace(old, new)
        revisions = r.get("revisions", [])
        revisions.append({
            "kind":       "bulk_replace",
            "old_word":   old, "new_word": new,
            "replaced":   cnt,
            "revised_at": today,
            "backup_id":  batch_id,
        })
        r["content"]   = new_content
        r["revisions"] = revisions
        rules[idx] = r

        # DB 재색인
        new_chunks = _reindex_rule_chunks(seq, title, dept, url, new_content)
        changed.append({"seq": seq, "title": title,
                         "replaced": cnt, "new_chunks": new_chunks})

    if not changed:
        raise HTTPException(400, "선택한 규정에서 해당 단어를 찾지 못했습니다.")

    # JSON 저장
    _save_rules_json(rules)

    # batch 백업 파일 저장 (한 번에 되돌리기용)
    backup = {
        "backup_id":    batch_id,
        "kind":         "bulk_replace",
        "title":        f"일괄 치환: '{old}' → '{new}' ({len(changed)}개 규정)",
        "old_word":     old, "new_word": new,
        "backed_up_at": datetime.now().isoformat(timespec="seconds"),
        "items":        backup_items,
    }
    with open(os.path.join(REVISION_BACKUP_DIR, f"{batch_id}.json"),
              "w", encoding="utf-8") as f:
        _json.dump(backup, f, ensure_ascii=False, indent=2)

    return {
        "success": True, "batch_id": batch_id,
        "old_word": old, "new_word": new,
        "rule_count": len(changed),
        "total_replaced": sum(c["replaced"] for c in changed),
        "changed": changed,
    }




# ══════════════════════════════════════════════════════════════════
# AI 형식/표현 검사 — 규정 본문이 한성대 표준 형식에 맞는지 검토
# ══════════════════════════════════════════════════════════════════

# 한성대 규정 표준 형식 (크롤링한 원문에서 파악한 규칙)
_HSU_RULE_FORMAT = """[한성대학교 규정 표준 형식]
- 조: '제 1 조 (목적)' — '제'와 숫자와 '조' 사이를 띄우고, 괄호 안에 조 제목.
- 항: 원문자 ① ② ③ 사용.
- 호: 숫자+마침표 '1.' '2.' '3.' 사용. ('가.' '나.' 같은 한글 기호를 호에 쓰지 않음)
- 목: 한글+마침표 '가.' '나.' '다.' 사용. (호 아래 하위 항목일 때만)
- 개정일: 조문 끝에 '(2025. 9. 23.)' 형태로 표기.
- 부칙: '부 칙' 표기 후 '(시행일) ...' 형태.
- 문장은 규정체(간결한 평서문, '~한다' '~하여야 한다')로 작성."""


class FormatCheckQ(BaseModel):
    text: str
    scope: str = "article"   # article | full | bulk — 안내 문구용


@app.post("/format-check")
def format_check(req: FormatCheckQ, payload: dict = Depends(verify_token)):
    """
    규정 본문을 AI가 검토해 표준 형식/표현에 어긋난 부분을 찾는다.
    반환: 각 지적사항 {snippet, kind(format|expression), advice}
      - snippet: 본문에서 문제가 되는 '정확한 원문 일부' (프론트가 찾아서 하이라이트)
      - kind: format = 형식 오류 / expression = 표현 제안
      - advice: 어떻게 고치면 좋은지 한 줄 조언
    """
    text = (req.text or "").strip()
    if len(text) < 5:
        raise HTTPException(400, "검사할 내용이 너무 짧습니다.")

    doc = text[:5000]   # 토큰 보호
    prompt = f"""너는 한성대학교 규정 편집을 돕는 검토 도우미다.
아래 규정 본문을 검토해, 표준 형식이나 표현에 어긋난 부분을 찾아라.

{_HSU_RULE_FORMAT}

[검토할 본문]
{doc}

[지시]
- 형식 오류(항/호/목 기호, 띄어쓰기, 개정일 표기 등)와 표현 제안(문장이 규정체가 아닌 경우 등)을 찾아라.
- 각 지적은 본문에 '실제로 있는 짧은 원문 조각'을 그대로 인용해야 한다 (찾아서 하이라이트할 것이므로 정확히).
- 문제가 없으면 빈 배열을 반환하라. 억지로 지적하지 마라.
- 표현 제안은 신중히, 명백히 어색한 경우만.
- 출력은 JSON 배열만. 설명·머리말 없이. 형식:
[
  {{"snippet": "가. 첫째 항목", "kind": "format", "advice": "호는 '가.'가 아니라 '1.' '2.' 순으로 씁니다."}},
  {{"snippet": "제1조(목적)", "kind": "format", "advice": "'제 1 조 (목적)'처럼 띄어 씁니다."}}
]
- kind 는 "format" 또는 "expression" 둘 중 하나.
- 지적은 최대 15개까지만."""

    try:
        resp = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        raw = _re.sub(r'^```[a-zA-Z]*\s*', '', raw)
        raw = _re.sub(r'\s*```$', '', raw).strip()
        # JSON 배열만 추출
        m = _re.search(r'\[.*\]', raw, _re.S)
        if m:
            raw = m.group(0)
        issues = _json.loads(raw)
        if not isinstance(issues, list):
            issues = []
    except Exception as e:
        return {"issues": [], "error": f"AI 검토 실패: {e}", "text": text}

    # 검증: snippet 이 실제 본문에 있는 것만 통과
    cleaned = []
    for it in issues:
        if not isinstance(it, dict):
            continue
        snip = (it.get("snippet") or "").strip()
        kind = it.get("kind", "format")
        advice = (it.get("advice") or "").strip()
        if not snip or not advice:
            continue
        if snip not in text:
            continue   # 본문에 없는 인용은 버림 (AI 환각 방지)
        if kind not in ("format", "expression"):
            kind = "format"
        cleaned.append({"snippet": snip, "kind": kind, "advice": advice})

    # 중복 snippet 제거
    seen = set()
    final = []
    for it in cleaned:
        if it["snippet"] in seen:
            continue
        seen.add(it["snippet"])
        final.append(it)

    return {"issues": final, "text": text, "count": len(final)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)