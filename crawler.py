"""
한성대학교 규정관리시스템 크롤러
- 세션 쿠키 기반 requests 크롤링
- SEQ 1~1000 순회
- 첨부파일(PDF / DOCX / HWP / HWPX) 텍스트 추출 지원
- 결과: hansung_rules.json

[필요 패키지]
pip install requests beautifulsoup4 pdfplumber python-docx pyhwp lxml
"""

import requests
import json
import re
import time
import zipfile
import tempfile
import subprocess
import io
from pathlib import Path
from bs4 import BeautifulSoup

BASE   = "https://rule.hansung.ac.kr"
OUTPUT = "hansung_rules.json"

# 브라우저에서 복사한 쿠키
COOKIES = {
    "_ga_K9JR8L935E": "GS2.1.s1755828368$o1$g0$t1755828376$j52$l0$h0",
    "_ga":             "GA1.1.1100685177.1755828368",
    "_ga_NL5KXSTFMR": "GS2.1.s1755828457$o1$g1$t1755828471$j46$l0$h0",
    "_ga_H9TXVM0LGL":  "GS2.1.s1778759247$o7$g1$t1778759502$j60$l0$h0",
    "_ga_2G1Q8E8S12":  "GS2.1.s1779073288$o88$g1$t1779074259$j60$l0$h0",
    "JSESSIONID":      "E6AA05A0CEB4E58BA051D003AA6F672B",
    "TS01e66883":      "014902a0e1b93d89217fc5457bcfa671c3a3d428f61691c130e3cd4ddc0d2d9fc57446eef383fa1fbc63aec1f0507306ad6241cf0e",
}

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer":         "https://rule.hansung.ac.kr/lmxsrv/main/main.do",
}

session = requests.Session()
session.cookies.update(COOKIES)
session.headers.update(HEADERS)


# ── 첨부파일 텍스트 추출 함수들 ───────────────────────────────────

def extract_pdf(data: bytes) -> str:
    """PDF 바이트 → 텍스트 (pdfplumber 사용)"""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() for page in pdf.pages if page.extract_text()]
            return "\n".join(pages)
    except ImportError:
        print("    ⚠️  pdfplumber 미설치: pip install pdfplumber")
        return ""
    except Exception as e:
        print(f"    ⚠️  PDF 추출 실패: {e}")
        return ""


def extract_docx(data: bytes) -> str:
    """DOCX 바이트 → 텍스트 (python-docx 사용, 표 포함)"""
    try:
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if row_text:
                    parts.append(row_text)
        return "\n".join(parts)
    except ImportError:
        print("    ⚠️  python-docx 미설치: pip install python-docx")
        return ""
    except Exception as e:
        print(f"    ⚠️  DOCX 추출 실패: {e}")
        return ""


def extract_hwpx(data: bytes) -> str:
    """HWPX 바이트 → 텍스트 (ZIP + XML 파싱, lxml 없어도 동작)"""
    try:
        texts = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            section_files = sorted(
                [f for f in z.namelist() if re.match(r'Contents/[Ss]ection\d+\.xml', f)]
            )
            if not section_files:
                section_files = [f for f in z.namelist()
                                 if f.endswith('.xml') and 'section' in f.lower()]

            for fname in section_files:
                xml_bytes = z.read(fname)
                # lxml 있으면 xml 파서, 없으면 html.parser 폴백
                try:
                    soup = BeautifulSoup(xml_bytes, "xml")
                except Exception:
                    soup = BeautifulSoup(xml_bytes, "html.parser")

                for tag in soup.find_all(re.compile(r'(?:hp:)?t$')):
                    txt = tag.get_text()
                    if txt.strip():
                        texts.append(txt)

        return "\n".join(texts)
    except Exception as e:
        print(f"    ⚠️  HWPX 추출 실패: {e}")
        return ""


def extract_hwp(data: bytes) -> str:
    """HWP 바이트 → 텍스트 (pyhwp CLI hwp5txt 사용)"""
    try:
        with tempfile.NamedTemporaryFile(suffix=".hwp", delete=False) as f:
            f.write(data)
            tmp_path = f.name

        result = subprocess.run(
            ["hwp5txt", tmp_path],
            capture_output=True,
            timeout=30,
            encoding="utf-8",
            errors="replace"
        )
        Path(tmp_path).unlink(missing_ok=True)

        if result.returncode == 0:
            return result.stdout
        else:
            print(f"    ⚠️  HWP 추출 실패 (code {result.returncode}): {result.stderr[:100]}")
            return ""
    except FileNotFoundError:
        print("    ⚠️  pyhwp 미설치: pip install pyhwp")
        return ""
    except Exception as e:
        print(f"    ⚠️  HWP 추출 실패: {e}")
        return ""


def _decode_filename(raw: str) -> str:
    """Content-Disposition 파일명 디코딩 (UTF-8 / EUC-KR 순 시도)"""
    raw = raw.strip().strip('"\'')
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.encode("latin-1").decode(enc)
        except Exception:
            continue
    return raw


def extract_attachment(data: bytes, filename: str) -> str:
    """확장자에 따라 적절한 추출 함수 호출"""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_pdf(data)
    elif ext == ".docx":
        return extract_docx(data)
    elif ext == ".hwpx":
        return extract_hwpx(data)
    elif ext == ".hwp":
        return extract_hwp(data)
    else:
        print(f"    ⚠️  지원하지 않는 형식: {ext}")
        return ""


# ── 첨부파일 수집 (이미 받은 view_soup 재사용) ──────────────────────

def get_attachments(view_soup: BeautifulSoup, seq: int, hist: str) -> list[dict]:
    """
    lawFullView 파싱 결과에서 javascript:fileDown('SEQ','TYPE') 링크 수집 후 다운로드·추출
    실제 다운로드: POST /lmxsrv/fileDown.do {FILE_SEQ, FILE_TYPE}
    """
    attachments = []
    try:
        for a in view_soup.find_all("a", href=True):
            href = a["href"]
            # javascript:fileDown('1301', 'ori') 패턴 감지
            m = re.match(r"javascript:fileDown\(['\"](\d+)['\"],\s*['\"](\w+)['\"]\)", href)
            if not m:
                continue

            file_seq  = m.group(1)
            file_type = m.group(2)   # 'ori' 또는 'oriPdf'

            # ori는 HWP/DOCX 원본, oriPdf는 PDF 버전 — 둘 다 수집
            # 같은 FILE_SEQ의 oriPdf는 ori 다음에 오므로 중복 내용이면 건너뜀
            if file_type == "oriPdf":
                # ori 이미 수집됐으면 PDF는 중복이므로 스킵
                if any(a.get("file_seq") == file_seq for a in attachments):
                    continue

            print(f"    📎 fileDown({file_seq}, {file_type}) 다운로드 중...")
            try:
                # POST 방식으로 다운로드
                resp = session.post(
                    f"{BASE}/lmxsrv/fileDown.do",
                    data={"FILE_SEQ": file_seq, "FILE_TYPE": file_type},
                    timeout=30
                )
                if resp.status_code != 200 or len(resp.content) < 100:
                    continue

                # Content-Type이 HTML이면 실패 (오류 페이지)
                ct = resp.headers.get("Content-Type", "")
                if "html" in ct.lower():
                    print(f"    ⚠️  HTML 응답 — 다운로드 실패 (세션 만료?)")
                    continue

                # 파일명 추출
                cd = resp.headers.get("Content-Disposition", "")
                cd_m = re.search(r"filename\*?=(?:UTF-8'')?([^;\n]+)", cd, re.I)
                fname = _decode_filename(cd_m.group(1)) if cd_m else f"file_{file_seq}.hwp"

                # 확장자 없으면 Content-Type으로 추정
                if "." not in fname.split("/")[-1]:
                    ext_map = {
                        "application/pdf":   ".pdf",
                        "application/msword":".doc",
                        "application/vnd.openxmlformats": ".docx",
                        "application/haansofthwp": ".hwp",
                        "application/x-hwp": ".hwp",
                    }
                    for k, v in ext_map.items():
                        if k in ct.lower():
                            fname += v; break
                    else:
                        fname += ".hwp"  # 기본값

                text = extract_attachment(resp.content, fname)
                if text.strip():
                    print(f"    ✅ {fname} 추출 완료 ({len(text)}자)")
                    attachments.append({"filename": fname, "text": text, "file_seq": file_seq})

            except Exception as e:
                print(f"    ⚠️  다운로드 실패 (FILE_SEQ={file_seq}): {e}")

    except Exception as e:
        print(f"    ⚠️  첨부파일 수집 실패: {e}")

    return attachments


# ── 규정 1개 크롤링 ──────────────────────────────────────────────

def crawl_one(seq: int) -> dict | None:
    """규정 1개 크롤링 (첨부파일 텍스트 포함)"""
    try:
        # 1. lawDetail.do → SEQ_HISTORY 파악
        r_detail = session.get(
            f"{BASE}/lmxsrv/law/lawDetail.do",
            params={"SEQ": seq, "PAGE_MODE": ""},
            allow_redirects=True, timeout=10
        )
        if r_detail.status_code >= 400:
            return None
        if "errorPage" in r_detail.url or len(r_detail.text) < 500:
            return None

        m = re.search(r'SEQ_HISTORY=(\d+)', r_detail.url)
        if m:
            hist = m.group(1)
        else:
            detail_soup = BeautifulSoup(r_detail.text, "html.parser")
            sel_el = detail_soup.find("select", {"id": "histroySeq"})
            opt = sel_el.find("option", selected=True) if sel_el else None
            if not opt:
                opt = sel_el.find("option") if sel_el else None
            m2 = re.search(r'SEQ_HISTORY=(\d+)', r_detail.text)
            hist = opt["value"] if opt else (m2.group(1) if m2 else None)

        if not hist:
            return None

        # 2. lawFullView → 제목 / 담당부서 / 첨부파일 링크
        r_view = session.get(
            f"{BASE}/lmxsrv/law/lawFullView.do?SEQ={seq}&SEQ_HISTORY={hist}",
            timeout=15, allow_redirects=True
        )
        if r_view.status_code >= 400 or "errorPage" in r_view.url:
            return None

        view_soup = BeautifulSoup(r_view.text, "html.parser")

        title = ""
        stit = view_soup.select_one(".Stit")
        if stit:
            title = re.sub(r'^\d+-\d+-\S+\s*', '', stit.get_text(strip=True)).strip()

        dept = ""
        dtit = view_soup.select_one(".Dtit")
        if dtit:
            dept = dtit.get_text(strip=True).replace("담당부서 :", "").strip()

        # 3. lawFullContent → 본문
        rc = session.get(
            f"{BASE}/lmxsrv/law/lawFullContent.do?SEQ={seq}&SEQ_HISTORY={hist}",
            timeout=15
        )
        if rc.status_code != 200:
            return None

        body = BeautifulSoup(rc.text, "html.parser").find("body")
        content = body.get_text("\n", strip=True) if body else ""

        # 4. 첨부파일 텍스트 추출 (view_soup 재사용 → 추가 요청 없음)
        attachments = get_attachments(view_soup, seq, hist)
        if attachments:
            attach_text = "\n\n".join(
                f"[첨부: {a['filename']}]\n{a['text']}" for a in attachments
            )
            content = (content + "\n\n" + attach_text).strip()

        if len(content) < 20:
            return None

        if not title or len(title) < 2:
            code_m = re.search(r'\d+-\d+-\d+\S*\s*\n\s*(.+)', content)
            title = code_m.group(1).strip() if code_m else ""
        if not title or len(title) < 2:
            return None

        attach_cnt = len(attachments)
        print(f"  ✅ SEQ={seq:4d} | {title[:45]}" + (f" | 첨부 {attach_cnt}건" if attach_cnt else ""))

        return {
            "seq":         seq,
            "seq_history": hist,
            "title":       title,
            "department":  dept,
            "category":    "",
            "content":     content,
            "attachments": [{"filename": a["filename"]} for a in attachments],
            "url":         f"{BASE}/lmxsrv/law/lawFullView.do?SEQ={seq}&SEQ_HISTORY={hist}"
        }

    except Exception as e:
        print(f"  ❌ SEQ={seq}: {e}")
        return None


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    results, done = [], set()

    if Path(OUTPUT).exists():
        results = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))
        done = {r["seq"] for r in results}
        print(f"기존 {len(results)}개 로드, 이어서 진행\n")

    target = [s for s in range(1, 1001) if s not in done]
    print(f"크롤링 대상: {len(target)}개 SEQ\n")

    for i, seq in enumerate(target):
        rule = crawl_one(seq)
        if rule:
            results.append(rule)

        if (i + 1) % 30 == 0:
            Path(OUTPUT).write_text(
                json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  💾 중간저장 ({len(results)}개 수집됨)\n")

        time.sleep(0.5)

    Path(OUTPUT).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n🎉 완료! {len(results)}개 규정 → {OUTPUT}")


if __name__ == "__main__":
    main()