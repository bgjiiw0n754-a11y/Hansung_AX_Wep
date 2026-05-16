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

INPUT     = "hansung_rules.json"
EMB_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
BATCH     = 64
DIM       = 384

print(f"모델 로딩 중: {EMB_MODEL}")
model = SentenceTransformer(EMB_MODEL)
print("모델 로딩 완료!")

def chunk_rule(rule):
    content = rule.get("content", "")
    code_m  = re.search(r"\d+-\d+-\d+\S*\s*\n\s*(.+)", content)
    title   = code_m.group(1).strip() if code_m else rule.get("title", "")
    seq     = str(rule.get("seq", ""))
    url     = rule.get("url", "")
    dept    = rule.get("department", "")
    pat     = re.compile(r'(제\s*\d+\s*조(?:의\s*\d+)?(?:\s*\([^)]*\))?)', re.M)
    parts   = pat.split(content)
    chunks  = []
    if len(parts) > 1:
        i = 1
        while i < len(parts) - 1:
            hdr  = parts[i].strip()
            body = parts[i+1].strip() if i+1 < len(parts) else ""
            if len(body) > 10:
                art = re.sub(r'\s+', '', hdr)
                chunks.append({"id": f"r{seq}_{art}", "text": f"[{title}] {hdr}\n{body[:1500]}", "rule_title": title, "seq": seq, "article": art, "department": dept, "url": url})
            i += 2
    if not chunks and len(content) > 20:
        chunks.append({"id": f"r{seq}_full", "text": f"[{title}]\n{content[:2000]}", "rule_title": title, "seq": seq, "article": "full", "department": dept, "url": url})
    return chunks

def main():
    rules = json.loads(Path(INPUT).read_text(encoding="utf-8"))
    print(f"{len(rules)} rules loaded")

    all_chunks = []
    for r in rules:
        all_chunks.extend(chunk_rule(r))
    print(f"{len(all_chunks)} chunks created")

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
    print("Table created")

    total = len(all_chunks)
    for i in range(0, total, BATCH):
        batch = all_chunks[i:i+BATCH]
        try:
            embeddings = model.encode([c["text"] for c in batch], normalize_embeddings=True).tolist()
            rows = [(c["id"], c["rule_title"], c["seq"], c["article"], c["department"], c["url"], c["text"], emb)
                    for c, emb in zip(batch, embeddings)]
            execute_values(cur, "INSERT INTO rule_chunks (id,rule_title,seq,article,department,url,content,embedding) VALUES %s ON CONFLICT (id) DO NOTHING", rows)
            conn.commit()
            print(f"  {min(i+BATCH, total)}/{total}")
        except Exception as e:
            print(f"  batch error: {e}")
            conn.rollback()

    cur.close()
    conn.close()
    print("Done!")

if __name__ == "__main__":
    main()