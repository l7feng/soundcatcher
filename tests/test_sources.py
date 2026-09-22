"""B5 来源文件夹（sources 表）纯逻辑测试：增 / 删 / 查 / 去重 / 迁移。

不启动 GUI、不加载模型：直接建一个临时库，走 db.init_db 建表后调用
AppBackend 的 slot（AppBackend 构造会起线程与模型，这里只测数据层语义，
因此直接操作 db 连接 + 复刻 slot 的 SQL 语义；slot 层的元对象存在性由
test_backend_contract.py 守护）。

用法::

    python tests/test_sources.py     # 结果写 tests/_sources.log
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

import soundcatcher.db as db  # noqa: E402

LOG = Path(__file__).resolve().parent / "_sources.log"
_lines: list[str] = []


def out(m: str = "") -> None:
    _lines.append(m)
    try:
        print(m, flush=True)
    except Exception:  # noqa: BLE001
        pass


def chk(cond: bool, msg: str) -> None:
    out(("  [OK ] " if cond else "  [FAIL] ") + msg)
    if not cond:
        raise AssertionError(msg)


def add_source(conn: sqlite3.Connection, path: str) -> str:
    """复刻 AppBackend.addSource 的 SQL 语义（去重 + 返回文案类别）。"""
    norm = str(Path(path).resolve())
    exists = conn.execute("SELECT 1 FROM sources WHERE path=?", (norm,)).fetchone()
    if exists:
        return "dup"
    conn.execute(
        "INSERT INTO sources(path, added_at, last_scan) VALUES(?, ?, '')",
        (norm, time.strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    return "added"


def list_sources(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT path FROM sources ORDER BY added_at ASC"
    ).fetchall()
    return [r["path"] for r in rows]


def remove_source(conn: sqlite3.Connection, path: str) -> None:
    conn.execute("DELETE FROM sources WHERE path=?", (path,))
    conn.commit()


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    dbfile = tmp / "library.db"
    conn = db.connect(dbfile)
    db.init_db(conn)

    out("=== B5 来源文件夹（sources 表）===")

    # ① 表存在 + 初始为空
    tbl = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
    ).fetchone()
    chk(tbl is not None, "sources 表已建（schema v3）")
    chk(list_sources(conn) == [], "初始来源表为空")

    # ② 添加两个真实存在的目录（用 tmp 下的子目录，保证 is_dir 语义）
    d1 = tmp / "lib1"
    d2 = tmp / "lib2"
    d1.mkdir()
    d2.mkdir()
    chk(add_source(conn, str(d1)) == "added", "添加来源 1 → added")
    chk(add_source(conn, str(d2)) == "added", "添加来源 2 → added")

    # ③ 去重：同路径（含相对/尾斜杠写法）不重复入库
    chk(add_source(conn, str(d1)) == "dup", "重复添加同一路径 → dup（去重生效）")
    chk(add_source(conn, str(d1) + "/") == "dup", "尾斜杠写法同样视为重复")
    chk(len(list_sources(conn)) == 2, "去重后仍为 2 条")

    # ④ PRIMARY KEY 兜底：直接 INSERT 同路径应抛 IntegrityError
    try:
        conn.execute(
            "INSERT INTO sources(path, added_at, last_scan) VALUES(?, 'x', '')",
            (str(d1.resolve()),),
        )
        conn.commit()
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    chk(raised, "path 主键唯一约束生效（直接 INSERT 重复抛 IntegrityError）")

    # ⑤ 查询返回登记顺序（added_at 升序），路径为绝对规范化
    got = list_sources(conn)
    chk(got[0] == str(d1.resolve()) and got[1] == str(d2.resolve()),
        "查询按登记顺序返回规范化绝对路径")

    # ⑥ 移除
    remove_source(conn, str(d1.resolve()))
    chk(list_sources(conn) == [str(d2.resolve())], "移除来源 1 后仅剩来源 2")
    remove_source(conn, "不存在的路径")   # 移除不存在项不报错
    chk(len(list_sources(conn)) == 1, "移除不存在的路径静默无副作用")

    # ⑦ 迁移幂等：旧库（v2，无 sources 表）再跑 init_db 应自动补表且不丢数据
    #
    # 要点：合成的 v2 库必须用**真实的 v2 表结构**，不能拿只有三列的精简 files 表顶替。
    # 原因：init_db 会无条件 executescript(SCHEMA)，其中 files_fts 的灌数语句
    # 引用了 files.ext 等列；若 files 表缺列，CREATE TABLE IF NOT EXISTS 又不会补列
    # → 报 `no such column: ext`。这里直接从现行 SCHEMA 里剔除 sources 段来还原 v2。
    conn.close()
    old = tmp / "old.db"
    c2 = db.connect(old)
    v2_schema = db.SCHEMA.split("-- B5：来源文件夹登记表")[0]
    c2.executescript(v2_schema)
    c2.executescript(
        """
        INSERT INTO meta(key, value) VALUES('schema_version', '2');
        INSERT INTO files(path, filename, ext) VALUES('/x/a.wav', 'a.wav', 'wav');
        """
    )
    c2.commit()
    had_before = c2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
    ).fetchone()
    db.init_db(c2)   # v2 → v3
    has_after = c2.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
    ).fetchone()
    ver = db.get_meta(c2, "schema_version")
    chk(had_before is None and has_after is not None, "v2 旧库迁移后补出 sources 表")
    chk(ver == "3", f"迁移后 schema_version=3（实际 {ver}）")
    # 迁移不丢数据：旧的 files 行仍在
    kept = c2.execute("SELECT COUNT(*) AS n FROM files").fetchone()["n"]
    chk(kept == 1, f"迁移保留原有 files 数据（实际 {kept} 行）")
    # 新表可用
    add_source(c2, str(d2))
    chk(list_sources(c2) == [str(d2.resolve())], "迁移后的库 sources 表可正常写入")
    c2.close()

    out("\n=== RESULT ===")
    out("  TEST_SOURCES OK")
    LOG.write_text("\n".join(_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except BaseException:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        _lines.append(traceback.format_exc())
        LOG.write_text("\n".join(_lines) + "\n", encoding="utf-8")
        rc = 1
    sys.exit(rc)
