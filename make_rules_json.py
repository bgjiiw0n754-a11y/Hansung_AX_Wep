"""
hansung_rules.json 생성기
============================================================
crawler.py 가 만든 hansung_rules_history.json (버전 이력 전체)에서
각 규정의 '최신판'만 추려서 hansung_rules.json 을 만든다.

  hansung_rules_history.json   ← 크롤러 출력 (versions 배열 = 개정 이력 전부)
        │  (이 스크립트)
        ▼
  hansung_rules.json           ← 개정 기능(server.py)이 쓰는 최신판 목록

사용법:
  1) python crawler.py        # hansung_rules_history.json 생성/갱신
  2) python make_rules_json.py  # 그걸로 hansung_rules.json 생성
  3) python build_db.py       # DB 재생성 (history 파일 사용)

※ 기존 hansung_rules.json 은 자동으로 .bak 으로 백업한 뒤 덮어쓴다.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime

HISTORY_FILE = "hansung_rules_history.json"
OUTPUT_FILE  = "hansung_rules.json"


def pick_latest(versions: list) -> dict | None:
    """versions 중 최신 버전 1개를 고른다."""
    if not versions:
        return None
    # 1) is_latest 플래그가 있으면 그것
    for v in versions:
        if v.get("is_latest"):
            return v
    # 2) 없으면 revision_date 가 가장 늦은 것
    dated = [v for v in versions if v.get("revision_date")]
    if dated:
        return max(dated, key=lambda v: v.get("revision_date", ""))
    # 3) 그래도 없으면 배열 첫 번째 (크롤러는 0번을 최신으로 둠)
    return versions[0]


def main():
    hist_path = Path(HISTORY_FILE)
    if not hist_path.exists():
        print(f"[오류] {HISTORY_FILE} 이(가) 없습니다. 먼저 crawler.py 를 실행하세요.")
        return

    try:
        regulations = json.loads(hist_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[오류] {HISTORY_FILE} 읽기 실패: {e}")
        return

    print(f"{len(regulations)}개 규정 로드 ({HISTORY_FILE})")

    rules = []
    skipped = []
    for reg in regulations:
        seq      = reg.get("seq")
        title    = reg.get("title", "")
        dept     = reg.get("department", "")
        url_late = reg.get("url_latest", "")
        latest   = pick_latest(reg.get("versions", []))

        if latest is None or not (latest.get("content") or "").strip():
            skipped.append((seq, title))
            continue

        rules.append({
            "seq":         seq,
            "seq_history": latest.get("seq_history", ""),
            "title":       title,
            "department":  dept,
            "category":    reg.get("category", ""),   # crawler/patch_categories가 채워둔 "제N편 ..." 값
            "chapter":     reg.get("chapter", 0),     # 편 번호 (1~8)
            "content":     latest.get("content", ""),
            "attachments": latest.get("attachments", []),
            "url":         url_late or latest.get("url", ""),
        })

    # seq 순 정렬
    rules.sort(key=lambda x: (x["seq"] is None, x["seq"]))

    # 기존 파일 백업
    out_path = Path(OUTPUT_FILE)
    if out_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = out_path.with_suffix(f".bak_{stamp}.json")
        shutil.copy2(out_path, bak)
        print(f"기존 {OUTPUT_FILE} → {bak.name} 으로 백업")

    out_path.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n완료: {OUTPUT_FILE} 생성 ({len(rules)}개 규정)")
    if skipped:
        print(f"  ⚠️ 본문이 없어 제외된 규정 {len(skipped)}개:")
        for seq, title in skipped[:10]:
            print(f"     - seq {seq}: {title}")
        if len(skipped) > 10:
            print(f"     ... 외 {len(skipped)-10}개")


if __name__ == "__main__":
    main()