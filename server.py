import os
import jwt
import shutil
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
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

# ── 환경 변수 ──────────────────────────────────────────────────────
GROQ_KEY   = os.getenv("GROQ_API_KEY")
DB_URL     = os.getenv("DATABASE_URL")

# SECRET_KEY: .env에 32자 이상으로 설정 권장. 미설정 시 자동 생성 (재시작마다 바뀜)
_raw_key   = os.getenv("SECRET_KEY", "")
SECRET_KEY = _raw_key if len(_raw_key) >= 32 else _secrets.token_hex(32)
if len(_raw_key) < 32:
    print("⚠️  SECRET_KEY가 짧거나 없습니다. .env에 32자 이상 랜덤 문자열을 추가하세요.")

# 관리자 계정 — .env에 ADMIN_ID / ADMIN_PW 추가하면 변경 가능
# 기본값: admin / 1234
ADMIN_ID = os.getenv("ADMIN_ID", "admin")
ADMIN_PW = os.getenv("ADMIN_PW", "1234")

if not GROQ_KEY:
    raise RuntimeError("❌ GROQ_API_KEY가 .env에 설정되지 않았습니다.")
if not DB_URL:
    raise RuntimeError("❌ DATABASE_URL이 .env에 설정되지 않았습니다.")

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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

security = HTTPBearer()

# ── teacher 라우터 연결 ─────────────────────────────────────────────
app.include_router(teacher_router)
set_ai_client(groq_client)

DEPT_PHONE = {
    "학사운영팀": "02-760-4114", "총무인사팀": "02-760-4114",
    "교수지원팀": "02-760-4114", "학생복지팀": "02-760-4114",
    "대학원 교학팀": "02-760-4114", "입학관리팀": "02-760-4114",
    "연구지원팀": "02-760-4114", "재무회계팀": "02-760-4114",
    "전략평가관리팀": "02-760-4114",
}

SYSTEM = """
당신은 한성대학교 규정 전문 안내 AI입니다.
10년 경력의 행정 담당자처럼 — 규정을 꿰뚫고 있으면서도 누구나 쉽게 이해하도록 친절하게 설명합니다.

━━━ 핵심 원칙 ━━━

▪ 제공된 [참고 규정 조항]을 유일한 근거로 사용합니다.
▪ 여러 조항이 관련되면 반드시 연계하여 설명합니다. 하나만 보지 말고 전체 맥락을 파악하세요.
▪ 규정 원문을 절대 그대로 옮기지 않습니다. 항상 자연스러운 한국어로 풀어 씁니다.
▪ "관련 규정이 없습니다"는 최후의 수단입니다. 유사 조항, 상위 규정, 준용 가능한 조항을 먼저 찾으세요.
▪ 반드시 한국어로만 답변합니다. 어떤 언어도 섞지 않습니다.

━━━ 출력 구조 ━━━

번호, 레이블, 마크다운(**, ##, 표) 절대 금지.
아래 흐름으로 자연스럽게 이어서 씁니다.

① 제목 (첫 줄, 레이블 없이)
   질문을 한 줄로 요약. 15자 이내 권장.
   나쁜 예: "1. 제목\n연가 안내" / 좋은 예: "교직원 연가 일수 및 사용 기준"

② 핵심 요약 (2~3문장)
   가장 중요한 내용을 먼저. 바쁜 사람이 첫 두 줄만 읽어도 핵심을 알 수 있게.

③ 상세 설명
   - 적용 대상, 조건, 절차, 기간, 금액 등 구체적인 수치와 기준을 포함합니다.
   - 예외사항, 특이사항, 주의점을 빠뜨리지 않습니다.
   - 실제 업무에서 어떻게 적용하는지 현실적인 맥락으로 설명합니다.
   - 복잡한 내용은 항목(-)으로 나눠 가독성을 높입니다.
   - 관련 조항이 여러 개라면 연결해서 설명합니다. ("이와 관련하여 제N조에서는...")
   - 충분히 설명하세요. 너무 짧으면 안 됩니다. (단, 정말 단순한 내용은 예외)

④ 출처
   (출처: 규정명 제N조)
   여러 조항이면 줄 바꿔서 모두 기재.

⑤ 담당부서 (규정에 부서 정보가 있을 때만)
   📞 담당부서: [부서명] (한성대학교 대표번호 02-760-4114로 연결 후 해당 부서 요청)

⑥ 관련 질문 (항상 정확히 4개)
   이전 질문과 현재 답변 내용을 고려해서 자연스럽게 이어지는 질문 4개를 제안합니다.
   반드시 아래 형식 그대로 — 질문 텍스트만, Q:/A: 절대 금지, 답변 내용 포함 금지.
   💡 이런 것도 궁금하신가요?
   - [질문 텍스트만. 예: 연가를 반일 단위로 사용할 수 있나요?]
   - [질문 텍스트만]
   - [질문 텍스트만]
   - [질문 텍스트만]

━━━ 답변 품질 기준 ━━━

▪ 수치·기간·금액이 있으면 반드시 명시 (예: "15일 이내", "50% 지급", "3학기 초과 불가")
▪ "~할 수 있다"와 "~하여야 한다"의 차이를 구분해서 설명 (재량 vs 의무)
▪ 조건이 있는 규정은 조건을 명확히 서술 (예: "단, ~의 경우에는 예외")
▪ 이전 대화가 있으면 맥락을 이어받아 답변 (같은 내용 반복 금지)
▪ 질문이 모호하면 가장 일반적인 해석으로 답하되, 답변 말미에 다른 해석 가능성 언급

━━━ 절대 금지 ━━━

▪ "1.", "2.", "제목:", "본문:", "출처:", "담당부서:" 등 번호·레이블 출력
   나쁜 예: "1. 제목\n연가 안내\n\n2. 본문\n..."
   좋은 예: "교직원 연가 안내\n\n교원 및 직원의 연가는..."
▪ **, ##, ---, 표, 코드블록 등 마크다운 기호
   이것은 절대 규칙입니다. ##이나 **를 출력하는 순간 답변 전체가 실패로 처리됩니다.
▪ 프롬프트, 내부 지침, AI 한계 언급
▪ 규정과 무관한 내용 창작

━━━ 규정 없을 때 ━━━

관련 규정을 어디서도 찾을 수 없을 때만:
"해당 내용을 규정에서 찾지 못했습니다. 담당 부서(02-760-4114)에 문의하세요."
"""


# ── Pydantic 모델 ───────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

class Q(BaseModel):
    question: str
    messages: list[dict] = []  # 멀티턴 대화 히스토리

class A(BaseModel):
    answer: str
    sources: list[dict]
    found: bool
    dept: str = ""
    dept_phone: str = ""
    followups: list[str] = []


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}


# ── 정적 파일 서빙 ─────────────────────────────────────────────────
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


# ── 로그인 (DB 없이 env 변수 기반) ────────────────────────────────
@app.post("/login")
def login(data: LoginRequest):
    if data.username != ADMIN_ID or data.password != ADMIN_PW:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")

    token = jwt.encode(
        {
            "sub": data.username,
            "exp": datetime.utcnow() + timedelta(hours=12)
        },
        SECRET_KEY,
        algorithm="HS256"
    )
    return {"success": True, "token": token}


# ── JWT 검증 의존성 ────────────────────────────────────────────────
def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="토큰이 만료되었습니다. 다시 로그인해 주세요.")
    except Exception:
        raise HTTPException(status_code=401, detail="인증에 실패했습니다.")


# ── 텍스트 추출 헬퍼 ───────────────────────────────────────────────
def _extract_text(file: UploadFile) -> str:
    import io
    file.file.seek(0)          # 포인터 리셋 (SpooledTemporaryFile 안전하게)
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
        raise HTTPException(400, "PDF 텍스트 추출 실패 (스캔본 제외, 텍스트 기반 PDF만 지원)")

    if fname.endswith(".docx") or "wordprocessingml" in ctype:
        from docx import Document as DocxDoc
        doc = DocxDoc(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

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

    # TXT 및 기타
    for enc in ["utf-8", "cp949", "euc-kr"]:
        try:
            return data.decode(enc).strip()
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore").strip()


def _chunk_text(text: str, max_len: int = 400) -> list[str]:
    """단락 기준으로 청크 분할, max_len 초과 시 문장 단위 재분할"""
    paragraphs = [p.strip() for p in _re.split(r'\n{2,}', text) if p.strip()]
    chunks = []
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) < max_len:
            buf = (buf + "\n" + para).strip() if buf else para
        else:
            if buf:
                chunks.append(buf)
            # 단락 자체가 너무 길면 문장 단위로 자름
            if len(para) > max_len:
                sentences = _re.split(r'(?<=[.!?])\s+', para)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) < max_len:
                        buf = (buf + " " + s).strip() if buf else s
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = s
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= 20]


def _extract_article_title(chunk: str, idx: int) -> str:
    """청크에서 조항 제목 추출 (제N조 패턴 우선)"""
    m = _re.search(r'(제\s*\d+\s*조(?:의\s*\d+)?\s*(?:\([^)]{1,30}\))?)', chunk)
    if m:
        return m.group(1).strip()[:60]
    first = chunk.split('\n')[0].strip()
    if 3 < len(first) <= 50:
        return first
    return f"청크 {idx + 1}"


# ── 규정 파일 업로드 & DB 등록 ─────────────────────────────────────
@app.post("/upload-regulation")
async def upload_regulation(
    file: UploadFile = File(...),
    payload: dict = Depends(verify_token)
):
    filename = file.filename or "unknown"
    upload_tag = f"upload://{filename}"

    # 0) 중복 업로드 체크
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM rule_chunks WHERE url = %s", (upload_tag,))
        if cur.fetchone()[0] > 0:
            conn.close()
            raise HTTPException(409, f'"{filename}"은(는) 이미 등록된 규정입니다. 삭제 후 다시 업로드하세요.')
        conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"DB 확인 실패: {e}")

    # 1) 텍스트 추출
    try:
        text = _extract_text(file)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"파일 읽기 실패: {e}")

    if not text or len(text.strip()) < 10:
        raise HTTPException(400, "파일에서 텍스트를 추출할 수 없습니다.")

    # 2) 청크 분할
    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(400, "청크 분할 실패: 내용이 너무 짧습니다.")

    # 3) 임베딩 생성
    try:
        embeddings = emb_model.encode(chunks, normalize_embeddings=True).tolist()
    except Exception as e:
        raise HTTPException(500, f"임베딩 생성 실패: {e}")

    # 3-1) 규정 편 분류 (Groq로 1~8편 판단)
    CHAP_MAP_UP = {
        "1": "학교법인", "2": "학칙", "3": "학사행정",
        "4": "부속기관", "5": "부설기관", "6": "위원회",
        "7": "산학협력단", "8": "학생군사교육단",
    }
    try:
        clf = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": f"""한성대학교 규정 체계에서 다음 문서가 속하는 편 번호(1~8)만 답하세요.
1편:학교법인  2편:학칙  3편:학사행정  4편:부속기관
5편:부설기관  6편:위원회  7편:산학협력단  8편:학생군사교육단
규정명: {filename}
내용: {text[:300]}
숫자 하나만 답하세요:"""}],
            max_tokens=3,
        )
        raw_clf = clf.choices[0].message.content.strip()
        m_clf   = _re.search(r'[1-8]', raw_clf)
        chap_num = m_clf.group(0) if m_clf else "3"
    except Exception:
        chap_num = "3"  # 분류 실패 시 학사행정(3편)으로

    dept_tag = f"업로드:{chap_num}"  # 예: "업로드:3"

    # 4) DB 삽입 — url 컬럼에 upload:// 태그로 식별
    upload_tag = f"upload://{filename}"
    inserted = 0
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()

        # id 컬럼이 TEXT 타입 — 타임스탬프 기반 고유 ID 생성
        import time as _time
        base_id = int(_time.time() * 1000)  # 밀리초 타임스탬프

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cur.execute("""
                INSERT INTO rule_chunks
                    (id, rule_title, article, department, url, content, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
            """, (
                str(base_id + i),
                filename,
                _extract_article_title(chunk, i),   # 조항 제목 파싱
                dept_tag,          # "업로드:N" — 편 분류 정보 포함
                upload_tag,
                chunk,
                str(emb)
            ))
            inserted += 1
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 저장 실패: {e}")

    # 5) 원본 파일 로컬 백업 (텍스트는 이미 읽었으므로 data 변수 재사용)
    os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)
    save_path = os.path.join(BASE_DIR, "uploads", filename)
    try:
        file.file.seek(0)
        with open(save_path, "wb") as f:
            f.write(file.file.read())
    except Exception:
        pass  # 백업 실패는 무시 (DB 저장이 주목적)

    return {"success": True, "filename": filename, "chunks": inserted}


# ── 업로드된 규정 목록 조회 ────────────────────────────────────────
@app.get("/uploaded-rules")
def list_uploaded_rules(payload: dict = Depends(verify_token)):
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("""
            SELECT url, COUNT(*) as cnt, MIN(id) as first_id
            FROM rule_chunks
            WHERE url LIKE 'upload://%'
            GROUP BY url
            ORDER BY first_id DESC
        """)
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    result = []
    for row in rows:
        tag, cnt, _ = row
        fname = tag.replace("upload://", "")
        result.append({"filename": fname, "chunks": cnt, "tag": tag})
    return {"rules": result}


# ── 업로드된 규정 삭제 ─────────────────────────────────────────────
@app.delete("/uploaded-rules/{filename:path}")
def delete_uploaded_rule(filename: str, payload: dict = Depends(verify_token)):
    tag = f"upload://{filename}"
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("DELETE FROM rule_chunks WHERE url = %s", (tag,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 삭제 실패: {e}")

    if deleted == 0:
        raise HTTPException(404, "해당 규정을 찾을 수 없습니다.")

    # 로컬 백업 파일도 삭제
    local = os.path.join(BASE_DIR, "uploads", filename)
    if os.path.exists(local):
        os.remove(local)

    return {"success": True, "filename": filename, "deleted_chunks": deleted}


# ── 규정 질의 ──────────────────────────────────────────────────────
@app.post("/query", response_model=A)
def query(req: Q):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "Empty question")

    try:
        expand_resp = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": f"""다음 질문에서 한국 대학 규정 검색에 쓸 핵심 키워드를 추출하세요.
동의어, 약어, 관련 법령 용어도 포함하세요. 쉼표로 구분해서 단어만 나열하세요. (예: 전과, 학과변경, 전공이동)

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
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, rule_title, article, department, url, content,
                   1 - (embedding <=> %s::vector) AS score
            FROM rule_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """, (qemb, qemb, TOP_K))
        rows = list(cur.fetchall())

        raw_keywords = [w for w in (q + ' ' + ' '.join(extra_keywords)).replace("?", "").split() if len(w) >= 3]
        keywords = list(raw_keywords)
        for w in raw_keywords:
            if len(w) >= 4:
                for i in range(0, len(w)-2, 2):
                    sub = w[i:i+3]
                    if sub not in keywords:
                        keywords.append(sub)

        if keywords:
            existing_ids = {r[0] for r in rows}
            for kw in keywords:
                cur.execute("SELECT id, rule_title, article, department, url, content, 0.85 AS score FROM rule_chunks WHERE article LIKE %s LIMIT %s", (f"%{kw}%", TOP_K))
                for r in cur.fetchall():
                    if r[0] not in existing_ids:
                        rows.append(r); existing_ids.add(r[0])
                cur.execute("SELECT id, rule_title, article, department, url, content, 0.7 AS score FROM rule_chunks WHERE content LIKE %s LIMIT %s", (f"%{kw}%", TOP_K))
                for r in cur.fetchall():
                    if r[0] not in existing_ids:
                        rows.append(r); existing_ids.add(r[0])

        rows = sorted(rows, key=lambda x: x[6], reverse=True)[:TOP_K]
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")

    if not rows or rows[0][6] < 0.15:
        return A(answer="해당 내용을 규정에서 찾지 못했습니다. 담당 부서에 문의하세요.", sources=[], found=False)

    ctx    = "\n\n".join([f"[조항 {i+1}] {r[1]} {r[2]}\n{r[5]}" for i, r in enumerate(rows)])

    # ── 멀티턴: 이전 대화 히스토리 포함 ──────────────────────────────
    groq_msgs = [{"role": "system", "content": SYSTEM}]

    # 이전 user/assistant 메시지 (최근 3턴 = 6개, system 제외)
    history = [m for m in req.messages if m.get("role") in ("user", "assistant")]
    # 마지막 user 메시지는 현재 질문이므로 제외하고 이전 것만
    prev = history[:-1][-6:] if len(history) > 1 else []
    for m in prev:
        groq_msgs.append({"role": m["role"], "content": m["content"]})

    # 현재 질문에 규정 컨텍스트 포함
    groq_msgs.append({
        "role": "user",
        "content": f"[참고 규정 조항]\n{ctx}\n\n[질문]\n{q}"
    })

    try:
        resp = groq_client.chat.completions.create(
            model=GEN_MODEL,
            messages=groq_msgs,
            max_tokens=1024,
        )
        answer = resp.choices[0].message.content
    except Exception as e:
        raise HTTPException(500, f"Generation error: {e}")

    sources = [{"title": r[1], "article": r[2], "department": r[3], "url": r[4], "score": round(r[6], 3)} for r in rows]

    import re as _re2
    dept = ""; dept_phone = ""; followups = []

    # ── 담당부서 추출 (📞 담당부서: 부서명 (...))
    dept_m = _re2.search(r'📞\s*담당부서\s*:\s*([^\n(]+)', answer)
    if dept_m:
        dept = dept_m.group(1).strip()
        for k, v in DEPT_PHONE.items():
            if k in dept:
                dept_phone = v; break
        if not dept_phone:
            dept_phone = "02-760-4114"

    # ── 관련 질문 추출 (💡 또는 "관련 질문:" 형식 모두 처리)
    fq_block = _re2.search(
        r'(?:💡[^\n]*|관련\s*질문\s*:?)\n([\s\S]+?)(?=\n\n|\Z)',
        answer
    )
    if fq_block:
        followups = []
        for line in fq_block.group(1).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            text = _re2.sub(r'^[-*•\d]+[.)]\s*', '', stripped).strip()
            text = _re2.sub(r'^Q:\s*', '', text, flags=_re2.IGNORECASE).strip()
            if _re2.match(r'^A:\s*', text, flags=_re2.IGNORECASE):
                continue
            if len(text) > 5:
                followups.append(text)
        followups = followups[:4]

    # ── 본문 정리 ─────────────────────────────────────────────────
    import re as _re2

    # 📞 담당부서 줄 제거
    clean_answer = _re2.sub(r'\n*📞[^\n]*담당부서[^\n]*', '', answer)
    # 💡 또는 관련 질문: 섹션 전체 제거
    clean_answer = _re2.sub(r'\n*(?:💡|관련\s*질문\s*:?)[\s\S]*', '', clean_answer)
    # 번호 레이블 제거
    clean_answer = _re2.sub(r'(?m)^\s*\d+\s*[.\)]\s*(제목|본문|출처|담당부서|관련\s*질문)[^\n]*\n?', '', clean_answer)
    clean_answer = _re2.sub(r'(?m)^(제목|본문)\s*[:：]\s*', '', clean_answer)

    # ── 마크다운 전면 제거 ──
    # ## 헤더 → 텍스트만 남김
    clean_answer = _re2.sub(r'(?m)^#{1,6}\s*(.+)$', r'\1', clean_answer)
    # **bold** / *italic* → 텍스트만
    clean_answer = _re2.sub(r'\*{1,3}([^*\n]+)\*{1,3}', r'\1', clean_answer)
    # __bold__ / _italic_ → 텍스트만
    clean_answer = _re2.sub(r'_{1,2}([^_\n]+)_{1,2}', r'\1', clean_answer)
    # --- 구분선 제거
    clean_answer = _re2.sub(r'(?m)^[-*_]{3,}\s*$', '', clean_answer)
    # > 인용 제거
    clean_answer = _re2.sub(r'(?m)^>\s*', '', clean_answer)
    # ` 코드 제거
    clean_answer = _re2.sub(r'`+([^`]*)`+', r'\1', clean_answer)

    clean_answer = _re2.sub(r'\n{3,}', '\n\n', clean_answer)
    clean_answer = clean_answer.strip()

    return A(answer=clean_answer, sources=sources, found=True,
             dept=dept, dept_phone=dept_phone, followups=followups)


# ── 규정 목록 ──────────────────────────────────────────────────────
@app.get("/rules")
def get_rules():
    CHAP_MAP = {
        "1": "학교법인", "2": "학칙", "3": "학사행정",
        "4": "부속기관", "5": "부설기관", "6": "위원회",
        "7": "산학협력단", "8": "학생군사교육단",
    }
    chapters = _defaultdict(list)

    # ── JSON 기반 기존 규정 ────────────────────────────────────────
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
                except:
                    continue
    except Exception:
        pass

    # ── DB 업로드 규정 — 편 분류해서 기존 챕터에 통합 ────────────
    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        cur.execute("""
            SELECT DISTINCT rule_title, url, department
            FROM rule_chunks WHERE url LIKE 'upload://%'
            ORDER BY rule_title
        """)
        for row in cur.fetchall():
            rule_title, url, department = row
            # department = "업로드:N" 형태에서 편 번호 추출
            m_chap = _re.search(r'업로드:([1-8])', department or '')
            chap_num  = m_chap.group(1) if m_chap else "3"
            chap_name = CHAP_MAP.get(chap_num, "학사행정")
            chap_key  = f"제{chap_num}편 {chap_name}"
            chapters[chap_key].append({
                "seq": 9999,
                "code": f"{chap_num}-upload",
                "name": f"📎 {rule_title}",   # 업로드 규정 표시
                "dept": "업로드 규정",
                "url": "", "uploaded": True
            })
        conn.close()
    except Exception:
        pass

    result = []
    for key in sorted(chapters.keys(), key=lambda x: (
        int(_re.search(r'제(\d+)편', x).group(1)) if _re.search(r'제(\d+)편', x) else
        (98 if x == "기타" else 99)
    )):
        result.append({"chapter": key, "rules": sorted(chapters[key], key=lambda x: x["code"])})
    return {"chapters": result, "total": sum(len(c["rules"]) for c in result)}


# ── 규정 내용 키워드 검색 ──────────────────────────────────────────
@app.post("/search-rules")
def search_rules(req: Q):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "Empty query")

    keywords = [w for w in q.split() if len(w) >= 2]
    if not keywords:
        keywords = [q]

    try:
        conn = psycopg2.connect(DB_URL)
        cur  = conn.cursor()
        rows = []
        seen = set()

        for kw in keywords[:5]:
            # 규정명 매칭
            cur.execute("""
                SELECT rule_title, article, department, url, content
                FROM rule_chunks WHERE rule_title LIKE %s LIMIT 20
            """, (f"%{kw}%",))
            for r in cur.fetchall():
                key = (r[0], r[1])
                if key not in seen:
                    rows.append(r); seen.add(key)

            # 본문 매칭
            cur.execute("""
                SELECT rule_title, article, department, url, content
                FROM rule_chunks WHERE content LIKE %s OR article LIKE %s LIMIT 30
            """, (f"%{kw}%", f"%{kw}%"))
            for r in cur.fetchall():
                key = (r[0], r[1])
                if key not in seen:
                    rows.append(r); seen.add(key)

        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB error: {e}")

    if not rows:
        return {"results": [], "query": q}

    # 규정명 단위로 그룹핑
    from collections import defaultdict as _dd
    grouped = _dd(list)
    for r in rows:
        grouped[r[0]].append({
            "article":    r[1],
            "department": r[2],
            "url":        r[3] or "",
            "snippet":    r[4][:200].strip(),
        })

    results = []
    for title, chunks in grouped.items():
        results.append({
            "title":      title,
            "department": chunks[0]["department"],
            "url":        chunks[0]["url"],
            "chunks":     chunks[:3]
        })

    return {"results": results[:20], "query": q}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)