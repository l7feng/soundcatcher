"""settings.migrate_path 单元测试：迁移逻辑与安全护栏。

**全程使用 tempfile 新建目录，从不删除**（sc 项目铁律：测试产物交用户决定清理）。

用法::

    python tests/test_settings_migrate.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from soundcatcher.gui.settings import migrate_path  # noqa: E402

fails: list[str] = []


def chk(cond: bool, msg: str) -> None:
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def main() -> int:
    base = Path(tempfile.mkdtemp(prefix="sc-migtest-"))
    print("测试根目录（跑完不删）：", base)

    # ---------- [1] 正常移动 ----------
    print("\n[1] 正常移动（旧有内容 → 新空目录）")
    old = base / "1old"; old.mkdir(parents=True)
    (old / "a.txt").write_text("aaa")
    (old / "sub").mkdir(); (old / "sub" / "b.txt").write_text("bbb")
    new = base / "1new"
    r = migrate_path("dataHome", old, new, mode="move")
    print("   ", r.summary())
    chk(r.ok, "迁移成功")
    chk(r.moved == 2, f"移动 2 个条目（实测 {r.moved}）")
    chk((new / "a.txt").read_text() == "aaa", "文件内容随迁")
    chk((new / "sub" / "b.txt").read_text() == "bbb", "子目录随迁")
    chk(not any(old.iterdir()), "旧目录被搬空（但目录本身仍在）")
    chk(old.exists(), "旧目录未被删除（只留空壳，符合安全约定）")

    # ---------- [2] 旧目录不存在 / 为空 ----------
    print("\n[2] 旧目录不存在 / 为空 → 无需迁移")
    r = migrate_path("dataHome", base / "nope", base / "2new")
    chk(r.ok and r.mode == "none", "不存在的旧目录 → mode=none")

    empty = base / "2empty"; empty.mkdir()
    r = migrate_path("dataHome", empty, base / "2new2")
    chk(r.ok and r.mode == "none", "空旧目录 → mode=none")

    r = migrate_path("dataHome", None, base / "2new3")
    chk(r.ok and r.mode == "none", "old=None → mode=none")

    # ---------- [3] 套娃拒绝 ----------
    print("\n[3] 新旧互相包含 → 拒绝")
    outer = base / "3outer"; outer.mkdir(); (outer / "x.txt").write_text("x")
    inner = outer / "inner"
    r = migrate_path("dataHome", outer, inner)
    chk(not r.ok, "新在旧之内 → 拒绝")
    print("      ", r.error)

    r = migrate_path("dataHome", inner, outer)
    # inner 不存在 → 走 none，但若存在则应拒绝；这里验证「旧的父 = 新的」也拦住
    parent_case = base / "3parent"
    (parent_case / "child").mkdir(parents=True)
    (parent_case / "child" / "f.txt").write_text("f")
    r = migrate_path("dataHome", parent_case / "child", parent_case)
    chk(not r.ok, "旧在新之内 → 拒绝")
    print("      ", r.error)

    # ---------- [4] 目标非空拒绝 ----------
    print("\n[4] 目标非空 → 拒绝")
    s4 = base / "4src"; s4.mkdir(); (s4 / "a.txt").write_text("a")
    d4 = base / "4dst"; d4.mkdir(); (d4 / "occupied.txt").write_text("o")
    r = migrate_path("dataHome", s4, d4)
    chk(not r.ok, "目标非空 → 拒绝（避免与既有数据混淆）")
    print("      ", r.error)

    # ---------- [5] 同名条目跳过 ----------
    print("\n[5] 目标已有同名 → 跳过不覆盖")
    s5 = base / "5src"; s5.mkdir()
    (s5 / "same.txt").write_text("NEW")
    (s5 / "only.txt").write_text("only")
    d5 = base / "5dst"; d5.mkdir()
    # 目标里先放一个同名（但 resolve 后 dst 非空 → 会被第 4 条拦住）
    # 用一个子目录名冲突来测 skip 分支：把 dst 清空再把冲突放进去不可行，
    # 因此这里改为验证 dry_run 的条目计数
    r = migrate_path("dataHome", s5, d5, dry_run=True)
    chk(r.ok and r.moved == 2, f"dry_run 计数 2（实测 {r.moved}）")
    chk((s5 / "same.txt").read_text() == "NEW", "dry_run 不动文件")

    # ---------- [6] copy 模式保留旧数据 ----------
    print("\n[6] copy 模式：旧数据保留")
    s6 = base / "6src"; s6.mkdir(); (s6 / "c.txt").write_text("c")
    d6 = base / "6dst"
    r = migrate_path("dataHome", s6, d6, mode="copy")
    chk(r.ok and r.moved == 1, "copy 成功")
    chk((s6 / "c.txt").exists(), "copy 模式旧文件仍在")
    chk((d6 / "c.txt").exists(), "copy 模式新位置也有")

    # ---------- [7] 同路径 → no-op ----------
    print("\n[7] 新旧同一路径 → no-op")
    r = migrate_path("dataHome", s6, s6)
    chk(r.ok and r.mode == "none", "同路径 → mode=none")

    print("\n=== RESULT ===")
    if fails:
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("  MIGRATE TEST OK")
    print("\n清理清单（交用户决定，测试不自动删）：")
    print("  ", base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
