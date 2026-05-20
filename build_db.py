import json, re, os, time, sys
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
import requests

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("❌ DATABASE_URL이 .env에 설정되지 않았습니다.")

UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")
if not UPSTAGE_API_KEY:
    raise RuntimeError("❌ UPSTAGE_API_KEY가 .env에 설정되지 않았습니다.")

INPUT     = "hansung_rules_history.json"
# Upstage solar-embedding-1-large: 4096차원, 한국어 특화
EMB_MODEL = "solar-embedding-1-large-passage"   # 적재용: 문서 임베딩
EMB_URL   = "https://api.upstage.ai/v1/solar/embeddings"
BATCH     = 32           # Upstage 요청당 적정 배치 크기 (토큰 한계 고려)
DIM       = 4096
SLEEP_MS  = 50           # rate-limit 회피 (요청 사이 50ms 대기)

print(f"Upstage 임베딩 사용: {EMB_MODEL} ({DIM}차원)")


def embed_batch(texts: list[str], retries: int = 3) -> list[list[float]]:
    """Upstage embeddings API 호출. 재시도 포함."""
    headers = {
        "Authorization": f"Bearer {UPSTAGE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": EMB_MODEL, "input": texts}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(EMB_URL, headers=headers, json=payload, timeout=60)
            if r.status_code == 429:
                # rate limit — exponential backoff
                wait = (attempt + 1) * 2
                print(f"    rate-limit, {wait}초 대기...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            return [d["embedding"] for d in data["data"]]
        except Exception as e:
            last_err = e
            print(f"    임베딩 오류 (시도 {attempt+1}): {e}")
            time.sleep((attempt + 1) * 2)
    raise RuntimeError(f"임베딩 실패 (3회 재시도): {last_err}")


def chunk_rule(regulation: dict) -> list[dict]:
    """
    규정 1개 (여러 버전 포함) → 청크 리스트
    - 버전별 본문 조항 청크
    - 규정 전체 개정이력 요약 청크 (1개) → "언제 개정됐나요?" 질문 대응
    """
    seq   = str(regulation.get("seq", ""))
    title = regulation.get("title", "")
    dept  = regulation.get("department", "")
    url   = regulation.get("url_latest", "")
    versions = regulation.get("versions", [])

    chunks = []

    # ── 1) 개정이력 요약 청크 ─────────────────────────────────────
    # "이 규정은 언제 개정됐나요?" 에 바로 답할 수 있도록
    if versions:
        history_lines = []
        for v in versions:
            date  = v.get("revision_date", "날짜 미상")
            rtype = v.get("revision_type", "개정")
            label = v.get("revision_label", "")
            tag   = "✅ 최신" if v.get("is_latest") else ""
            history_lines.append(f"  - {date} {rtype} {tag} ({label})")

        history_text = (
            f"[{title}] 개정 이력\n"
            f"총 {len(versions)}회 개정 (제정 포함)\n"
            + "\n".join(history_lines)
        )

        # 개정이력 테이블 요약도 있으면 추가
        rev_table = regulation.get("revision_history_table", [])
        if rev_table:
            table_lines = [f"  - {r.get('date','')} {r.get('type','')} {r.get('summary','')}"
                           for r in rev_table if r.get("date")]
            if table_lines:
                history_text += "\n\n개정 내용 요약:\n" + "\n".join(table_lines)

        chunks.append({
            "id":         f"r{seq}_history",
            "text":       history_text,
            "rule_title": title,
            "seq":        seq,
            "article":    "개정이력",
            "department": dept,
            "url":        url,
        })

    # ── 2) 버전별 본문 청크 ───────────────────────────────────────
    pat = re.compile(r'(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)', re.M)

    for v in versions:
        content   = v.get("content", "")
        hist      = v.get("seq_history", "")
        rev_date  = v.get("revision_date", "")
        rev_type  = v.get("revision_type", "개정")
        is_latest = v.get("is_latest", False)
        v_url     = v.get("url", url)

        # 버전 태그 (최신 / 구버전 구분)
        ver_tag = f"[최신: {rev_date}]" if is_latest else f"[{rev_date} {rev_type}]"

        # 조항 단위 분할
        parts = pat.split(content)
        ver_chunks = []

        if len(parts) > 1:
            i = 1
            while i < len(parts) - 1:
                hdr  = parts[i].strip()
                body = parts[i + 1].strip() if i + 1 < len(parts) else ""
                if len(body) > 10:
                    art = re.sub(r'\s+', '', hdr)
                    ver_chunks.append({
                        "id":         f"r{seq}_h{hist}_{art}",
                        "text":       f"[{title}] {ver_tag} {hdr}\n{body[:1500]}",
                        "rule_title": title,
                        "seq":        seq,
                        "article":    f"{art} ({rev_date})",
                        "department": dept,
                        "url":        v_url,
                    })
                i += 2

        # 조항 분할 안 되면 전문 청크
        if not ver_chunks and len(content) > 20:
            ver_chunks.append({
                "id":         f"r{seq}_h{hist}_full",
                "text":       f"[{title}] {ver_tag}\n{content[:2000]}",
                "rule_title": title,
                "seq":        seq,
                "article":    f"전문 ({rev_date})",
                "department": dept,
                "url":        v_url,
            })

        chunks.extend(ver_chunks)

    return chunks


def main():
    regulations = json.loads(Path(INPUT).read_text(encoding="utf-8"))
    print(f"{len(regulations)}개 규정 로드")

    all_chunks = []
    for reg in regulations:
        all_chunks.extend(chunk_rule(reg))
    print(f"{len(all_chunks)}개 청크 (중복 제거 전)")

    # ── 중복 id 제거 — 같은 청크가 여러 번 잡히는 거 방지 ──
    seen_ids = set()
    deduped = []
    for c in all_chunks:
        cid = c["id"]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        deduped.append(c)
    all_chunks = deduped
    print(f"{len(all_chunks)}개 청크 (중복 제거 후)")

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    cur.execute("DROP TABLE IF EXISTS rule_chunks;")
    cur.execute(f"""
        CREATE TABLE rule_chunks (
            id         TEXT PRIMARY KEY,
            rule_title TEXT,
            seq        TEXT,
            article    TEXT,
            department TEXT,
            url        TEXT,
            content    TEXT,
            embedding  vector({DIM})
        );
    """)
    conn.commit()
    print("테이블 생성 완료")

    total = len(all_chunks)
    print(f"\n임베딩 + 적재 시작: 총 {total}개 청크 (배치 크기 {BATCH})")
    print(f"예상 소요: 약 {total // BATCH * 1.5 / 60:.0f}~{total // BATCH * 3 / 60:.0f}분")
    print()

    success = 0
    for i in range(0, total, BATCH):
        batch = all_chunks[i:i + BATCH]
        try:
            # Upstage는 4000자 이하 권장 — 너무 긴 청크는 잘라서 보냄
            texts = [(c["text"] or "")[:8000] for c in batch]
            embeddings = embed_batch(texts)

            if len(embeddings) != len(batch):
                print(f"  ⚠️ 응답 개수 불일치 ({len(embeddings)} vs {len(batch)}), 스킵")
                continue

            rows = [
                (c["id"], c["rule_title"], c["seq"], c["article"],
                 c["department"], c["url"], c["text"], emb)
                for c, emb in zip(batch, embeddings)
            ]
            execute_values(
                cur,
                "INSERT INTO rule_chunks (id,rule_title,seq,article,department,url,content,embedding) "
                "VALUES %s ON CONFLICT (id) DO NOTHING",
                rows
            )
            conn.commit()
            success += len(rows)
            done = min(i + BATCH, total)
            pct = done / total * 100
            print(f"  [{done:>5}/{total}] {pct:5.1f}% — 누적 성공 {success}")
            time.sleep(SLEEP_MS / 1000.0)
        except Exception as e:
            print(f"  ❌ 배치 오류 ({i}~{i+BATCH}): {e}")
            conn.rollback()

    cur.close()
    conn.close()
    print(f"\n✅ 완료! 총 {total}개 중 {success}개 청크 → DB 저장")


if __name__ == "__main__":
    main()