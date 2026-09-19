"""程序化验证 UCS 分类树数据：按 Category 聚合计数（GUI UcsTreeModel 的同一数据源）。

不依赖看图的程序化验证：直接查 ucs_labels 卷计数，并模拟树的 Category→子类两层聚合。
"""
import sys
sys.path.insert(0, "src")

from soundcatcher.config import Config
from soundcatcher import db
from soundcatcher.ucs import UcsCatalog

cfg = Config.default()
conn = db.connect(cfg.db_path)
db.init_db(conn)

# 每 file_id 的 top1 catid
top1 = conn.execute(
    """
    SELECT l.catid FROM ucs_labels l
    JOIN (SELECT file_id, MAX(confidence) mc FROM ucs_labels
          WHERE source='classifier' GROUP BY file_id) t
      ON t.file_id = l.file_id AND l.confidence = t.mc
    """
).fetchall()
counts: dict[str, int] = {}
for r in top1:
    counts[r["catid"]] = counts.get(r["catid"], 0) + 1

# Catalog 提供 catid -> category 映射（模拟树的父聚合）
catalog = UcsCatalog(cfg.catalog_dir)
cidx = catalog.catid_index()
cat_agg: dict[str, tuple[int, int]] = {}  # category -> (子类数, 文件数)
total_files = len(top1)
for catid, n in counts.items():
    cat = catalog[cidx[catid]].category
    if cat not in cat_agg:
        cat_agg[cat] = (0, 0)
    cat_agg[cat] = (cat_agg[cat][0] + 1, cat_agg[cat][1] + n)

print(f"有 top1 标签的文件数: {total_files}")
print(f"命中的子类数: {len(counts)} / 753")
print("\nTop 12 根分类（父聚合，GUI 树同源）:")
for cat, (subs, n) in sorted(cat_agg.items(), key=lambda kv: -kv[1][1])[:12]:
    print(f"  {cat:10s} 子类 {subs:4d}  文件 {n:6d}  ({n / total_files:.1%})")

# 未命中的子类（树里计数为 0 的）
unhit = [e.catid for e in catalog.entries if e.catid not in counts]
print(f"\n未命中子类: {len(unhit)} 个（树中显示 0）")
print("  示例:", ", ".join(unhit[:10]))