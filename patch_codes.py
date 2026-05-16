"""
기존 hansung_rules.json에 rule_code 필드 추가
lawFullView에서 규정 코드(1-0-1 등)만 빠르게 가져옴
"""
import requests, json, re, time
from pathlib import Path
from bs4 import BeautifulSoup

BASE = "https://rule.hansung.ac.kr"
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
session = requests.Session()
session.cookies.update(COOKIES)
session.headers.update({"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9"})

rules = json.loads(Path("hansung_rules.json").read_text(encoding="utf-8"))
print(f"{len(rules)}개 규정 로드")

patched = 0
for i, r in enumerate(rules):
    if r.get("rule_code"):
        continue  # 이미 있으면 스킵

    seq  = r["seq"]
    hist = r["seq_history"]
    try:
        resp = session.get(f"{BASE}/lmxsrv/law/lawFullView.do?SEQ={seq}&SEQ_HISTORY={hist}", timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        stit = soup.select_one(".Stit")
        if stit:
            m = re.search(r'(\d+-\d+-\S+)', stit.get_text())
            if m:
                r["rule_code"] = m.group(1).strip()
                patched += 1
    except Exception as e:
        print(f"  SEQ={seq} 실패: {e}")

    if (i+1) % 50 == 0:
        Path("hansung_rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  중간저장 ({i+1}/{len(rules)}, 패치:{patched}개)")
    time.sleep(0.3)

Path("hansung_rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n완료! {patched}개 규정에 rule_code 추가됨")
