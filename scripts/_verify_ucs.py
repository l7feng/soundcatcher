import sys
sys.path.insert(0, "src")
from soundcatcher.config import Config
from soundcatcher import db

cfg = Config.default()
conn = db.connect(cfg.db_path)
db.init_db(conn)

total = conn.execute("SELECT COUNT(DISTINCT file_id) c FROM ucs_labels").fetchone()["c"]
rows = conn.execute("SELECT COUNT(*) c FROM ucs_labels").fetchone()["c"]
srcs = conn.execute("SELECT source, COUNT(*) c FROM ucs_labels GROUP BY source").fetchall()
cats = conn.execute(
    "SELECT catid, COUNT(*) c FROM ucs_labels GROUP BY catid ORDER BY c DESC LIMIT 15"
).fetchall()
tags = conn.execute(
    "SELECT COUNT(*) c FROM tags WHERE auto=1 AND tag LIKE 'ucs:%'"
).fetchone()["c"]
fts = conn.execute("SELECT COUNT(*) c FROM files_fts WHERE tags LIKE '%ucs:%'").fetchone()["c"]

print(f"ucs_labels 文件数: {total} / 总行数: {rows}")
for s in srcs:
    print(f"  source={s['source']}: {s['c']}")
print(f"自动 ucs 标签行数: {tags}")
print(f"FTS 含 ucs 标签的文件数: {fts}")
print("Top 15 分类:")
for r in cats:
    print(f"  {r['catid']}: {r['c']}")