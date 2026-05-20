import json, re, os
from pathlib import Path
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_values
from sentence_transformers import SentenceTransformer

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("❌ DATABASE_URL이 .env에 설정되지 않았습니다.")

INPUT     = "hansung_rules_history.json"
EMB_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
BATCH     = 64
DIM       = 384

print(f"모델 로딩 중: {EMB_MODEL}")
model = SentenceTransformer(EMB_MODEL)
print("모델 로딩 완료!")


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
    print(f"{len(all_chunks)}개 청크 생성")

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
    for i in range(0, total, BATCH):
        batch = all_chunks[i:i + BATCH]
        try:
            embeddings = model.encode(
                [c["text"] for c in batch], normalize_embeddings=True
            ).tolist()
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
            print(f"  {min(i + BATCH, total)}/{total}")
        except Exception as e:
            print(f"  배치 오류: {e}")
            conn.rollback()

    cur.close()
    conn.close()
    print(f"\n✅ 완료! {total}개 청크 → DB 저장")


if __name__ == "__main__":
    main()