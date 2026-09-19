"""UCS 全量打标守护式分块脚本（断点续跑、块级事务、幂等）。

背景
----
``soundcatcher ucs tag`` 对全部已嵌入文件一次性分类，且**最后才 commit**
（cli.py 里的实现：整个 10.8 万条的写循环完成后才 ``conn.commit()``）。
长任务若被中断，全部回滚 → 白跑 30~40 分钟。本项目定案（坑 10）
要求长任务「分块前台执行、增量幂等、断点无损」，故本脚本按
``embedded=1`` 且**尚无 ucs_labels** 的文件，按 id 升序分块处理：
每块 = 取向量 → 分类 → 写 ucs_labels + tags + 刷 FTS，**块内一个事务**。

断点语义
--------
已存在 ``ucs_labels`` 行的文件视为已打标，跳过（含早前 80 文件测试产物
与 GUI 人工改标 manual 行）。因此脚本可从任意中断点续跑，重复运行安全。

用法（分块前台执行）::

    python scripts/run_ucs_tag.py                 # 全量跑完剩余未打标文件
    python scripts/run_ucs_tag.py --chunk 2000    # 自定义块大小（默认 5000）
    python scripts/run_ucs_tag.py --max-files 5000   # 只跑前 5000 条（试跑）
    python scripts/run_ucs_tag.py --topk 5        # 每文件保留分类数（默认 3，与 CLI 一致）
    python scripts/run_ucs_tag.py --status        # 只看进度，不处理

产物
----
- 日志：``data/ucs_tag_runner.log``（UTF-8，追加）
- 终态：``data/ucs_tag_runner.status``（running / ok / failed + 摘要）
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
LOG_FILE = DATA / "ucs_tag_runner.log"
STATUS_FILE = DATA / "ucs_tag_runner.status"

sys.path.insert(0, str(REPO / "src"))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{_now()}  {msg}\n")


def _write_status(text: str) -> None:
    STATUS_FILE.write_text(text, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="UCS 全量打标（守护式分块）")
    ap.add_argument("--chunk", type=int, default=5000, help="每块文件数（默认 5000）")
    ap.add_argument("--max-files", type=int, default=0, help="最多处理条数（0=全部，试跑用）")
    ap.add_argument("--topk", type=int, default=3, help="每文件保留分类数（默认 3）")
    ap.add_argument("--min-score", type=float, default=0.0, help="标签最低余弦分（默认 0.0）")
    ap.add_argument("--status", action="store_true", help="只看进度不处理")
    args = ap.parse_args()

    from soundcatcher.config import Config
    from soundcatcher import db
    from soundcatcher.indexer import VectorIndex
    from soundcatcher.ucs import UcsClassifier

    cfg = Config.default()
    cfg.ensure()

    conn = db.connect(cfg.db_path)
    db.init_db(conn)

    # 已打标集合（断点）
    done_ids = {
        int(r["file_id"])
        for r in conn.execute("SELECT DISTINCT file_id FROM ucs_labels").fetchall()
    }
    all_count = conn.execute(
        "SELECT COUNT(*) c FROM files WHERE embedded=1"
    ).fetchone()["c"]
    pending_count = all_count - len(done_ids)

    if args.status:
        print(f"已嵌入总计 {all_count}；已有标签 {len(done_ids)}；待打标 {pending_count}")
        return 0

    if pending_count <= 0:
        print(f"没有待打标文件（共 {all_count} 条，已全部打标），无需执行。")
        _write_status("ok\nnothing to do\n")
        return 0

    try:
        classifier = UcsClassifier.from_dir(cfg.ucs_dir, top_k=args.topk)
    except (FileNotFoundError, ValueError) as exc:
        log(f"!! 分类器加载失败：{exc}")
        _write_status(f"failed\n{exc}\n")
        return 1

    index = VectorIndex(cfg.index_path)
    log(f"分类器就绪（{len(classifier.catalog)} 类）；已嵌入 {all_count} "
        f"已有标签 {len(done_ids)} 待打标 {pending_count}")

    # 待处理列表（id 升序，跳过已打标）
    rows = conn.execute(
        "SELECT id, filename FROM files WHERE embedded=1 ORDER BY id"
    ).fetchall()
    todo = [(int(r["id"]), r["filename"]) for r in rows if int(r["id"]) not in done_ids]
    if args.max_files > 0:
        todo = todo[: args.max_files]
        log(f"试跑模式：限定 {args.max_files} 条")

    t0 = time.time()
    n_total = len(todo)
    n_tagged = 0
    n_below = 0
    _write_status(f"running\n待打标 {n_total}\n")

    try:
        for start in range(0, n_total, args.chunk):
            chunk = todo[start : start + args.chunk]
            ids = [fid for fid, _ in chunk]
            vecs = index.vectors_by_id(ids)
            results = classifier.classify_vectors(vecs)

            # ---- 块内一个事务 ----
            conn.execute("BEGIN")
            for fid, res in zip(ids, results):
                for entry, score, conf in res:
                    conn.execute(
                        """INSERT INTO ucs_labels(file_id, catid, confidence, source)
                           VALUES (?,?,?,?)
                           ON CONFLICT(file_id, catid) DO UPDATE SET
                               confidence=excluded.confidence, source=excluded.source""",
                        (fid, entry.catid, float(score), "classifier"),
                    )
                top = res[0]
                if float(top[1]) >= args.min_score:
                    e = top[0]
                    db.add_tag(conn, fid, f"ucs:{e.catid}", auto=True)
                    db.add_tag(conn, fid, f"ucs:{e.display_zh}", auto=True)
                    for s in e.synonyms_zh[:3]:
                        db.add_tag(conn, fid, s, auto=True)
                    n_tagged += 1
                else:
                    n_below += 1
                db.refresh_fts_tags(conn, fid)
            conn.commit()

            done = min(start + args.chunk, n_total)
            el = time.time() - t0
            rate = done / el if el > 0 else 0
            log(
                f"[{done}/{n_total}] 块完成（{len(chunk)} 条，"
                f"累计 {el:.0f}s，{rate:.1f} 条/s）"
            )
            _write_status(
                f"running\n[{done}/{n_total}] {el:.0f}s {rate:.1f} 条/s\n"
            )
    except Exception:
        msg = traceback.format_exc()
        log("!! 打标异常（traceback 见下）：\n" + msg)
        _write_status("failed\n" + msg)
        return 1

    el = time.time() - t0
    summary = (
        f"UCS 分类完成：{len(todo)} 个文件 → {len(classifier.catalog)} 类"
        f"，写入标签 {n_tagged}，低于阈值未写标签 {n_below}"
        f" | 耗时 {el:.0f}s（{n_total / el:.1f} 条/s）"
    )
    log(summary)
    _write_status(f"ok\n{summary}\n")

    # 终态抽样（前 12，供一眼验证）
    sample = conn.execute(
        """SELECT f.filename, l.catid, l.confidence, l.source
           FROM ucs_labels l JOIN files f ON f.id=l.file_id
           WHERE l.source='classifier'
           ORDER BY l.file_id, l.confidence DESC
           LIMIT 12"""
    ).fetchall()
    for r in sample:
        log(f"  [sample] {r['filename'][:50]} → {r['catid']} "
            f"(conf={r['confidence']:.3f}, {r['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())