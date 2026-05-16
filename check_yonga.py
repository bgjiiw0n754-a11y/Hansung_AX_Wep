import psycopg2, os
from dotenv import load_dotenv
load_dotenv()

conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("SELECT rule_title, article, content FROM rule_chunks WHERE content LIKE '%연가%' LIMIT 5")
rows = cur.fetchall()
print(f'연가 포함 청크: {len(rows)}개')
for r in rows:
    print(r[0], '|', r[1])
    print(r[2][:200])
    print('---')
conn.close()
