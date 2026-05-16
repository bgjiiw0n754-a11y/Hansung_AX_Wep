"""
한성대학교 규정관리시스템 크롤러
- 세션 쿠키 기반 requests 크롤링
- SEQ 1~400 순회
- 결과: hansung_rules.json
"""

import requests
import json
import re
import time
from pathlib import Path
from bs4 import BeautifulSoup

BASE   = "https://rule.hansung.ac.kr"
OUTPUT = "hansung_rules.json"

# 브라우저에서 복사한 쿠키
COOKIES = {
    "_ga_NL5KXSTFMR": "GS2.1.s1765006600$o5$g1$t1765007153$j3$l0$h0",
    "_ga_H9TXVM0LGL":  "GS2.1.s1775622375$o19$g1$t1775622537$j60$l0$h0",
    "_ga_2G1Q8E8S12":  "GS2.1.s1775978953$o173$g1$t1775978956$j57$l0$h0",
    "_gid":            "GA1.3.2034186977.1775979147",
    "ssotoken":        "Vy3zFyENGINEx5F1zTyGIDx5FDEMO1zCy1775979147zPy86400zAy43zEylUlUTMKgVgRSJon9MiUM1QNIN4XJcYeuwlNc0OHnx78tEkgwRnh27dVECnhx7ABcFEbHzKyQ8W56mQ5wG2OPL7rGBa5jL8K08eMx7Ap7VnNtnEp9jTldhE22LD4eP9ESG6kRnx796x7AbzSSy00000000110zUURyb52247d1a034737czMyUpTx79CqNx78SYcx3Dz",
    "TS01ae1b10":      "014902a0e13e051effbabe62c549cfba216ef762146c7590f873171b379eb329b2616f5255eb726343cc69192fd4e98663dc1f4d0b",
    "_ga_K9JR8L935E":  "GS2.1.s1775979147$o8$g1$t1775979148$j59$l0$h0",
    "_ga":             "GA1.1.751206202.1764537554",
    "JSESSIONID":      "409F817DFF00899E8D0A705E9F07F470",
    "TS01e66883":      "014902a0e1a6edfae25c50bc8ad863131cac3c8b0f98f4038c0f2101f70f0454bc6eec8c6bf5ebb73f145812f6d5c1b402cdbac0e6",
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


def get_latest_seq_history(seq: int) -> str | None:
    """규정 상세 페이지에서 최신 SEQ_HISTORY 파악"""
    try:
        # lawDetail로 최신 SEQ_HISTORY redirect 확인
        r = session.get(
            f"{BASE}/lmxsrv/law/lawDetail.do",
            params={"SEQ": seq, "PAGE_MODE": ""},
            allow_redirects=True,
            timeout=10
        )
        m = re.search(r'SEQ_HISTORY=(\d+)', r.url)
        if m:
            return m.group(1)
        # URL에 없으면 HTML에서 파싱
        m = re.search(r'SEQ_HISTORY[=\'\"]+(\d+)', r.text)
        return m.group(1) if m else None
    except:
        return None


def crawl_one(seq: int) -> dict | None:
    """규정 1개 크롤링"""
    try:
        # 1. lawDetail.do로 최신 SEQ_HISTORY 파악 (HTML에서 select 옵션 파싱)
        r_detail = session.get(
            f"{BASE}/lmxsrv/law/lawDetail.do",
            params={"SEQ": seq, "PAGE_MODE": ""},
            allow_redirects=True, timeout=10
        )
        if r_detail.status_code >= 400:
            return None
        if "errorPage" in r_detail.url or len(r_detail.text) < 500:
            return None

        # SEQ_HISTORY: URL에서 먼저, 없으면 HTML select에서
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

        # 2. lawFullView로 제목/담당부서 파악
        r_view = session.get(
            f"{BASE}/lmxsrv/law/lawFullView.do?SEQ={seq}&SEQ_HISTORY={hist}",
            timeout=15, allow_redirects=True
        )
        if r_view.status_code >= 400 or "errorPage" in r_view.url:
            return None

        view_soup = BeautifulSoup(r_view.text, "html.parser")

        # 제목: .Stit 클래스 (lawFullView에 있음)
        title = ""
        stit = view_soup.select_one(".Stit")
        if stit:
            title = stit.get_text(strip=True)
            # 앞의 규정번호 코드 제거 (예: "1-0-1학교법인...")
            title = re.sub(r'^\d+-\d+-\S+\s*', '', title).strip()

        # 담당부서
        dept = ""
        dtit = view_soup.select_one(".Dtit")
        if dtit:
            dept = dtit.get_text(strip=True).replace("담당부서 :", "").strip()

        # 3. lawFullContent.do로 실제 본문 수집
        rc = session.get(
            f"{BASE}/lmxsrv/law/lawFullContent.do?SEQ={seq}&SEQ_HISTORY={hist}",
            timeout=15
        )
        if rc.status_code != 200:
            return None

        content_soup = BeautifulSoup(rc.text, "html.parser")
        body = content_soup.find("body")
        content = body.get_text("\n", strip=True) if body else ""

        if len(content) < 20:
            return None

        # title 못 찾았으면 content에서 추출
        if not title or len(title) < 2:
            code_m = re.search(r'\d+-\d+-\d+\S*\s*\n\s*(.+)', content)
            title = code_m.group(1).strip() if code_m else ""
        if not title or len(title) < 2:
            return None

        print(f"  ✅ SEQ={seq:4d} | {title[:50]}")
        return {
            "seq":        seq,
            "seq_history": hist,
            "title":      title,
            "department": dept,
            "category":   "",
            "content":    content,
            "url":        f"{BASE}/lmxsrv/law/lawFullView.do?SEQ={seq}&SEQ_HISTORY={hist}"
        }

    except Exception as e:
        print(f"  ❌ SEQ={seq}: {e}")
        return None


def main():
    results, done = [], set()

    if Path(OUTPUT).exists():
        results = json.loads(Path(OUTPUT).read_text(encoding="utf-8"))
        done = {r["seq"] for r in results}
        print(f"기존 {len(results)}개 로드, 이어서 진행\n")

    # SEQ 1~1000 순회 (없는 SEQ는 자동 스킵)
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