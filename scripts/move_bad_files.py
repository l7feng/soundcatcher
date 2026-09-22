"""坏文件处置：把 DB 标记为 error 的源文件移入整理区 _to_clean/（不删除）。

背景（2026-09-18 人类拍板 A 方案）：
- 全量扫描识别 311 个坏文件（源文件损坏，0.27%），先移入整理区等人工确认。
- 红线：不删除任何文件；移动可逆。

行为：
- 从 `D:\音效库` 下按相对路径搬入 `_to_clean/<rel>`（保留目录结构，避免同名冲突）。
- 生成登记清单 `_to_clean/坏文件登记清单.md` 与移动日志。
- **不写 library.db**：DB 行保留，等人类确认删除后统一清理（files 级联删 fts/tags/ucs_labels）。

用法：python scripts/move_bad_files.py [--bad-json <path>] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from soundcatcher.config import Config  # noqa: E402

SRC_ROOT = Path(r"D:\音效库")
# 整理区随工程走：仓根 _to_clean/（2026-09-22 起由 App-Project\Sound-library 迁入仓内）
DST_ROOT = Config.default().home / "_to_clean"
# 待整理清单的默认落点：随工程走（data/ 已在 .gitignore，属运行态）
DEFAULT_JSON = Config.default().home / "data" / "bad_files.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad-json", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--dry-run", action="store_true", help="只统计不移动")
    args = ap.parse_args()

    rows = json.loads(args.bad_json.read_text(encoding="utf-8"))
    print(f"清单载入: {len(rows)} 条")

    moved: list[tuple[int, str, str]] = []  # (id, src, dst)
    skipped: list[tuple[int, str, str]] = []  # 非干跑时可复用 skipped 记录 missing/outside

    for r in rows:
        src = Path(r["path"])
        fid = int(r["id"])
        if not src.is_relative_to(SRC_ROOT):
            skipped.append((fid, str(src), "outside-root"))
            continue
        if not src.exists():
            skipped.append((fid, str(src), "missing"))
            continue
        rel = src.relative_to(SRC_ROOT)
        dst = DST_ROOT / rel
        if args.dry_run:
            moved.append((fid, str(src), str(dst)))
            continue
        if dst.exists():
            skipped.append((fid, str(src), "dst-exists"))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moved.append((fid, str(src), str(dst)))

    print(f"移动: {len(moved)}  跳过: {len(skipped)}")
    for fid, src, why in skipped:
        print(f"  SKIP id={fid} [{why}] {src}")

    if args.dry_run:
        return 0

    # 登记清单（markdown，供人工确认）
    DST_ROOT.mkdir(parents=True, exist_ok=True)
    top_dirs = Counter()
    for _, src, dst in moved:
        rel = Path(dst).relative_to(DST_ROOT)
        top_dirs[rel.parts[0]] += 1

    lines = [
        "# 坏文件登记清单（移入整理区，待人工确认）",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 来源：`D:\\音效库`（CLAP 全量扫描识别，源文件损坏 `avcodec_send_packet Invalid data`）",
        f"- 数量：**{len(moved)} 个**（DB error 行 311，与清单一致）",
        f"- 处置：已移入本目录 `_to_clean/`，**未删除**；人工确认后删除（同时清理 library.db 对应行）",
        "",
        "## 目录分布",
        "",
        "| 顶层目录 | 数量 |",
        "| --- | --- |",
    ]
    for d, n in top_dirs.most_common():
        lines.append(f"| `{d}` | {n} |")
    lines += ["", "## 明细", "", "| ID | 原路径 | 大小 | 错误 |", "| --- | --- | --- | --- |"]
    for fid, src, _ in moved:
        r = next(x for x in rows if int(x["id"]) == fid)
        err = (r["error"] or "").split("：")[-1][:60]
        size = f"{r['size']/1024:.1f} KB"
        lines.append(f"| {fid} | `{src}` | {size} | {err} |")

    manifest = DST_ROOT / "坏文件登记清单.md"
    manifest.write_text("\n".join(lines), encoding="utf-8")
    print(f"登记清单: {manifest}")

    # 移动日志（追加）
    log = DST_ROOT / "move.log"
    with log.open("a", encoding="utf-8") as f:
        for fid, src, dst in moved:
            f.write(f"{datetime.now().isoformat()} {fid} {src} -> {dst}\n")
    print(f"移动日志: {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())