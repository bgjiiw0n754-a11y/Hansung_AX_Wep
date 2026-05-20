import json
d = json.load(open("hansung_rules.json", encoding="utf-8"))
print(f"규정 수: {len(d)}")
print(f"chapter 필드 있음: {sum(1 for r in d if r.get('chapter'))} / {len(d)}")
print(f"category 필드 있음: {sum(1 for r in d if r.get('category'))} / {len(d)}")
from collections import Counter
c = Counter(r.get('chapter', 0) for r in d)
for ch in sorted(c.keys()):
    print(f"  chapter={ch}: {c[ch]}편")
