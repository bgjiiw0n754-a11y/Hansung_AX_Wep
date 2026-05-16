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

from pdfminer.high_level import extract_text_to_fp
from pdfminer.layout import LAParams
from docx import Document as DocxDocument
from docx.shared import Pt, RGBColor
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

def _db_url():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(500, "DATABASE_URL이 .env에 설정되지 않았습니다.")
    return url

def set_ai_client(client):
    pass  # 호환성 유지용 (미사용)

def _client():
    from groq import Groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise HTTPException(500, "GROQ_API_KEY가 .env에 없습니다.")
    return Groq(api_key=key)


# ── 텍스트 추출 ──────────────────────────────
def _extract(file: UploadFile) -> str:
    data  = file.file.read()
    fname = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()

    is_pdf  = fname.endswith(".pdf") or "pdf" in ctype
    is_docx = fname.endswith(".docx") or "wordprocessingml" in ctype
    is_txt  = fname.endswith(".txt") or "text/plain" in ctype

    if is_pdf:
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(io.BytesIO(data))
            if text and text.strip():
                return text.strip()
        except:
            pass
        raise HTTPException(400, "PDF 텍스트 추출 실패. 텍스트 기반 PDF(스캔본 제외)만 지원합니다.")

    elif is_docx:
        doc = DocxDocument(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    elif is_txt:
        for enc in ["utf-8", "cp949", "euc-kr"]:
            try:
                return data.decode(enc).strip()
            except:
                continue
        return data.decode("utf-8", errors="ignore").strip()

    raise HTTPException(400, "지원 형식: PDF, DOCX, TXT")


# ── POST /conflict/ ──────────────────────────
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

    # DB에서 관련 규정 검색
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

    rules_ctx = "\n\n".join(f"[{r['title']} {r['article']}]\n{r['content']}" for r in related[:10])

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


# ── POST /export/pdf ─────────────────────────
class ExportReq(BaseModel):
    title:    str = "규정 답변 리포트"
    content:  str
    sources:  list[dict] = []
    question: str = ""

@router.post("/export/pdf")
def export_pdf(req: ExportReq):
    buf = io.BytesIO()

    # Windows malgun.ttf, Linux NanumGothic, fallback Helvetica
    font_name = "Helvetica"
    for fp in [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/gulim.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ]:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("KR", fp))
                font_name = "KR"
            except:
                pass
            break

    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm)

    def ps(name, size, color="#000000", sa=6):
        return ParagraphStyle(name, fontName=font_name, fontSize=size,
            spaceAfter=sa, textColor=colors.HexColor(color), leading=size*1.6)

    def safe(t):
        return (t or "").replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\n','<br/>')

    story = [
        Paragraph("한성대학교 규정 마스터 AI", ps("s0",10,"#6B7A99")),
        Paragraph(req.title or "규정 답변 리포트", ps("s1",15,"#003087",sa=8)),
        HRFlowable(width="100%",thickness=1,color=colors.HexColor("#003087"),spaceAfter=12),
    ]
    if req.question:
        story += [Paragraph("[ 질문 ]", ps("s2",11,"#003087",sa=4)),
                  Paragraph(safe(req.question), ps("s3",11,sa=10))]
    story.append(Paragraph("[ 답변 ]", ps("s4",11,"#003087",sa=4)))
    for line in (req.content or "").split("\n"):
        if line.strip():
            story.append(Paragraph(safe(line), ps("s5",11,sa=4)))
    if req.sources:
        story += [Spacer(1,8),
                  HRFlowable(width="100%",thickness=0.5,color=colors.HexColor("#D1DCF0"),spaceAfter=6),
                  Paragraph("[ 참조 조항 ]", ps("s6",10,"#003087",sa=4))]
        for s in req.sources:
            score = int(s.get("score",0)*100)
            story.append(Paragraph(
                f"• {s.get('title','')} {s.get('article','')} (유사도 {score}%)",
                ps("s7",9,"#6B7A99",sa=3)))

    doc.build(story)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="hansung_report.pdf"'})


# ── POST /export/docx ────────────────────────
@router.post("/export/docx")
def export_docx(req: ExportReq):
    doc = DocxDocument()

    def heading(text, level, color=(0, 48, 135)):
        h = doc.add_heading(text, level=level)
        if h.runs:
            h.runs[0].font.color.rgb = RGBColor(*color)
        return h

    heading(req.title, 1)
    doc.add_paragraph("한성대학교 규정 마스터 AI")
    doc.add_paragraph("─" * 50)

    if req.question:
        heading("질문", 2)
        doc.add_paragraph(req.question)

    heading("답변", 2)
    for line in req.content.split('\n'):
        if line.strip():
            doc.add_paragraph(line)

    if req.sources:
        doc.add_paragraph("─" * 50)
        heading("참조 조항", 2)
        for s in req.sources:
            score = int(s.get('score', 0) * 100)
            p = doc.add_paragraph(style='List Bullet')
            run = p.add_run(f"{s.get('title','')}  {s.get('article','')}  (유사도 {score}%)")
            run.font.size = Pt(10)
            run.font.color.rgb = RGBColor(107, 122, 153)

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="hansung_report.docx"'})