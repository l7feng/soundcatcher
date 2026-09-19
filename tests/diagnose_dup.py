"""诊断：扫描后为何出现重复的检索结果。"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
c = sqlite3.connect(str(ROOT / "data" / "library.db"))
c.row_factory = sqlite3.Row

print("总行数:", c.execute("SELECT COUNT(*) n FROM files").fetchone()["n"])
print("唯一路径:", c.execute("SELECT COUNT(DISTINCT path) n FROM files").fetchone()["n"])

dup_path = c.execute(
    "SELECT path, COUNT(*) n FROM files GROUP BY path HAVING n>1"
).fetchall()
print("同 path 重复行:", len(dup_path))

print("\n同文件名多路径：")
rows = c.execute(
    "SELECT filename, COUNT(*) n, GROUP_CONCAT(path, ' || ') paths "
    "FROM files GROUP BY filename HAVING n>1 ORDER BY n DESC LIMIT 10"
).fetchall()
for r in rows:
    print(f"  {r['filename']!r} x{r['n']}")
    for p in r["paths"].split(" || "):
        print(f"      {p}")

print("\n样例路径（前 6）：")
for r in c.execute("SELECT id, path FROM files ORDER BY id LIMIT 6"):
    print(f"  {r['id']}: {r['path']}")

# faiss 索引里的 id 分布
import faiss  # noqa: E402

idx = faiss.read_index(str(ROOT / "data" / "index" / "vectors.faiss"))
print(f"\nfaiss ntotal = {idx.ntotal}")
idmap = faiss.vector_to_array(idx.id_map)
uniq = len(set(idmap.tolist()))
print(f"faiss 唯一 id 数 = {uniq}（若 < ntotal 说明有重复 id）")
