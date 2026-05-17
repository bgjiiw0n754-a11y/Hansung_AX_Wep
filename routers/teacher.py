"""
routers/teacher.py — 교직원 전용 기능
  POST /conflict/   : 문서 업로드 → 기존 규정과 충돌 분석
  POST /export/pdf  : 선택 답변 → PDF 다운로드
  POST /export/docx : 선택 답변 → DOCX 다운로드
"""
import os, io, re, json
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pdfminer.high_level import extract_text
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import psycopg2

router = APIRouter(tags=["teacher"])

GEN_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# ── PDF 폰트: 서버 시작 시 1회 초기화 ──────────────────────────────
_PDF_FONT = "Helvetica"

def _init_pdf_font():
    global _PDF_FONT
    # 이미 한글 폰트 등록됐으면 스킵
    try:
        pdfmetrics.getFont("KR")
        _PDF_FONT = "KR"
        return
    except Exception:
        pass

    # 폰트 후보 (Windows → Linux → Mac 순)
    candidates = [
        "C:/Windows/Fonts/malgun.ttf",      # 맑은 고딕 (Windows 10/11)
        "C:/Windows/Fonts/malgunbd.ttf",     # 맑은 고딕 Bold
        "C:/Windows/Fonts/batang.ttc",       # 바탕체 (ttc 제외)
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/System/Library/Fonts/AppleGothic.ttf",
    ]

    for fp in candidates:
        if not os.path.exists(fp):
            continue
        if fp.endswith(".ttc"):
            continue  # TTC 컬렉션은 TTFont 단독 등록 불가 → 스킵
        try:
            pdfmetrics.registerFont(TTFont("KR", fp))
            _PDF_FONT = "KR"
            return
        except Exception:
            continue

_init_pdf_font()  # 모듈 임포트 시 1회 실행


def _db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(500, "DATABASE_URL이 .env에 설정되지 않았습니다.")
    return url

def set_ai_client(client):
    pass  # 호환성 유지용

def _client():
    from groq import Groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(500, "GROQ_API_KEY가 .env에 없습니다.")
    return Groq(api_key=key)


# ── 텍스트 추출 ────────────────────────────────────────────────────
def _extract(file: UploadFile) -> str:
    file.file.seek(0)
    data  = file.file.read()
    fname = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()

    if fname.endswith(".pdf") or "pdf" in ctype:
        try:
            text = extract_text(io.BytesIO(data))
            if text and text.strip():
                return text.strip()
        except Exception:
            pass
        raise HTTPException(400, "PDF 텍스트 추출 실패. 텍스트 기반 PDF만 지원합니다.")

    if fname.endswith(".docx") or "wordprocessingml" in ctype:
        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    if fname.endswith(".json"):
        try:
            items = json.loads(data.decode("utf-8"))
            if isinstance(items, list):
                return "\n".join(" ".join(str(v) for v in item.values() if v)
                                 for item in items if isinstance(item, dict))
            return json.dumps(items, ensure_ascii=False)
        except Exception as e:
            raise HTTPException(400, f"JSON 파싱 실패: {e}")

    for enc in ["utf-8", "cp949", "euc-kr"]:
        try:
            return data.decode(enc).strip()
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore").strip()


# ── POST /conflict/ ───────────────────────────────────────────────
class ConflictReport(BaseModel):
    summary: str
    conflicts: list[dict]
    recommendations: str
    filename: str

@router.post("/conflict/", response_model=ConflictReport)
async def analyze_conflict(file: UploadFile = File(...)):
    doc_text = _extract(file)
    if not doc_text:
        raise HTTPException(400, "텍스트 추출 실패")

    related = []
    try:
        conn = psycopg2.connect(_db_url())
        cur  = conn.cursor()
        words = [w for w in re.sub(r'[^\w\s]', ' ', doc_text).split() if len(w) >= 3]
        for kw in list(dict.fromkeys(words))[:20]:
            cur.execute(
                "SELECT rule_title, article, content FROM rule_chunks WHERE content LIKE %s LIMIT 2",
                (f"%{kw}%",)
            )
            for row in cur.fetchall():
                e = {"title": row[0], "article": row[1], "content": row[2][:400]}
                if e not in related:
                    related.append(e)
            if len(related) >= 12:
                break
        conn.close()
    except Exception as e:
        raise HTTPException(500, f"DB 오류: {e}")

    rules_ctx = "\n\n".join(
        f"[{r['title']} {r['article']}]\n{r['content']}" for r in related[:10]
    )

    prompt = f"""당신은 한성대학교 규정 전문가입니다.
아래 [업로드 문서]와 [기존 규정]을 비교하여 충돌·불일치를 분석하세요.

[업로드 문서]
{doc_text[:3000]}

[기존 규정]
{rules_ctx}

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "summary": "전체 요약 2-3문장",
  "conflicts": [
    {{"regulation": "규정명", "article": "조항", "issue": "충돌 내용", "severity": "높음|보통|낮음"}}
  ],
  "recommendations": "개선 권고사항"
}}"""

    try:
        resp = _client().chat.completions.create(
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1500,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"summary": raw[:300], "conflicts": [], "recommendations": "AI 응답 파싱 실패"}
    except Exception as e:
        raise HTTPException(500, f"AI 분석 실패: {e}")

    return ConflictReport(
        summary         = parsed.get("summary", ""),
        conflicts       = parsed.get("conflicts", []),
        recommendations = parsed.get("recommendations", ""),
        filename        = file.filename or "문서"
    )


# ── POST /export/pdf ──────────────────────────────────────────────
class ExportReq(BaseModel):
    title:    str = "규정 답변 리포트"
    content:  str
    sources:  list[dict] = []
    question: str = ""

@router.post("/export/pdf")
def export_pdf(req: ExportReq):
    buf = io.BytesIO()
    fn  = _PDF_FONT  # "KR" or "Helvetica"

    def ps(name, size, color="#1A2340", sa=6, leading=None):
        return ParagraphStyle(
            name, fontName=fn, fontSize=size, spaceAfter=sa,
            textColor=colors.HexColor(color),
            leading=leading or size * 1.65
        )

    def safe(t: str) -> str:
        return (t or "").replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>')

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2.2*cm, rightMargin=2.2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm)

    story = []

    # 헤더
    story.append(Paragraph("한성대학교 규정 마스터 AI", ps("meta", 9, "#6B7A99", sa=4)))
    story.append(Paragraph(safe(req.title or "규정 답변 리포트"), ps("title", 16, "#003087", sa=10)))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#003087"), spaceAfter=14))

    # 질문
    if req.question:
        story.append(Paragraph("질문", ps("qlabel", 10, "#003087", sa=4)))
        story.append(Paragraph(safe(req.question), ps("qtxt", 11, "#1A2340", sa=12)))

    # 답변
    story.append(Paragraph("답변", ps("alabel", 10, "#003087", sa=6)))
    for line in (req.content or "").split("\n"):
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 4))
            continue
        # 출처 라인은 색 달리
        if stripped.startswith("(출처"):
            story.append(Paragraph(safe(stripped), ps("src", 9, "#0050B3", sa=3)))
        else:
            story.append(Paragraph(safe(stripped), ps("body", 11, "#1A2340", sa=4)))

    # 참조 조항
    if req.sources:
        story.append(Spacer(1, 10))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#D1DCF0"), spaceAfter=8))
        story.append(Paragraph("참조 조항", ps("srclabel", 10, "#003087", sa=6)))
        for s in req.sources:
            score = int(float(s.get("score", 0)) * 100)
            line  = f"• {s.get('title','')}  {s.get('article','')}  (유사도 {score}%)"
            story.append(Paragraph(safe(line), ps("srcitem", 9, "#6B7A99", sa=3)))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="hansung_report.pdf"'})


# ── POST /export/docx ─────────────────────────────────────────────
def _set_font(run, name="맑은 고딕", size=None):
    """run에 한글 폰트 직접 지정"""
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if size:
        run.font.size = Pt(size)

def _add_para(doc, text, font="맑은 고딕", size=10.5, bold=False, color=None, style=None):
    p = doc.add_paragraph(style=style)
    run = p.add_run(text)
    _set_font(run, font, size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    return p

@router.post("/export/docx")
def export_docx(req: ExportReq):
    doc = DocxDocument()

    # 기본 Normal 스타일에 한글 폰트 적용
    normal = doc.styles["Normal"]
    normal.font.name = "맑은 고딕"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    normal.font.size = Pt(10.5)

    # 제목
    h = doc.add_heading(req.title or "규정 답변 리포트", level=1)
    if h.runs:
        _set_font(h.runs[0], "맑은 고딕", 16)
        h.runs[0].font.color.rgb = RGBColor(0, 48, 135)

    _add_para(doc, "한성대학교 규정 마스터 AI", size=9, color=(107, 122, 153))
    doc.add_paragraph()

    # 질문
    if req.question:
        _add_para(doc, "[ 질문 ]", size=11, bold=True, color=(0, 48, 135))
        _add_para(doc, req.question, size=11)
        doc.add_paragraph()

    # 답변
    _add_para(doc, "[ 답변 ]", size=11, bold=True, color=(0, 48, 135))
    for line in (req.content or "").split("\n"):
        stripped = line.strip()
        if not stripped:
            doc.add_paragraph()
            continue
        color = (0, 80, 179) if stripped.startswith("(출처") else None
        size  = 9 if stripped.startswith("(출처") else 11
        _add_para(doc, stripped, size=size, color=color)

    # 참조 조항
    if req.sources:
        doc.add_paragraph()
        _add_para(doc, "[ 참조 조항 ]", size=11, bold=True, color=(0, 48, 135))
        for s in req.sources:
            score = int(float(s.get("score", 0)) * 100)
            text  = f"• {s.get('title','')}  {s.get('article','')}  (유사도 {score}%)"
            _add_para(doc, text, size=9, color=(107, 122, 153))

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="hansung_report.docx"'})