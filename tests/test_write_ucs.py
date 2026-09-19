"""UCS 改标写回 + 收藏导入 纯逻辑测试（无需 Qt/GUI/模型）。

覆盖：
- ``apply_ucs_relabel`` 写回：删旧自动 label → 写 manual → 重建 ucs:* 标签族 → 刷 FTS；
- 写连接方案：``_connect_writer`` 为短连接，busy_timeout/WAL/FK 已设；
- ``load_catid_map`` / ``flat_catalog_list`` 从 data-test/ucs/catalog.json（753 类）构建；
- ``UserDataStore.import_favorites``：md / csv / m3u / 纯路径列表，去重置顶、上限裁剪。

用法::

    python tests/test_write_ucs.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from soundcatcher import db  # noqa: E402
from soundcatcher.gui.backend import (  # noqa: E402
    _connect_writer,
    apply_ucs_relabel,
    flat_catalog_list,
    load_catid_map,
)
from soundcatcher.gui.userdata import MAX_FAVORITES, UserDataStore  # noqa: E402


def _make_lib(tmp: Path) -> None:
    """临时小库：2 文件 + 自动 ucs_labels + 自动标签。"""
    conn = db.connect(tmp / "library.db")
    db.init_db(conn)
    f1 = db.upsert_file(conn, path=r"C:\x\gunshot.wav", filename="gunshot.wav",
                        ext="wav", size=10, mtime=1.0, duration=1.0)
    f2 = db.upsert_file(conn, path=r"C:\x\ambience.wav", filename="ambience.wav",
                        ext="wav", size=11, mtime=1.0, duration=2.0)
    # 自动分类与自动标签
    for fid, catid in ((f1, "GUNShotg"), (f2, "AMBRoom")):
        conn.execute(
            "INSERT INTO ucs_labels(file_id, catid, confidence, source) VALUES(?,?,?,?)",
            (fid, catid, 0.8, "classifier"),
        )
        db.add_tag(conn, fid, f"ucs:{catid}", auto=True)
        db.add_tag(conn, fid, "boom", auto=True)
    db.refresh_fts_tags(conn, f1)
    db.refresh_fts_tags(conn, f2)
    conn.commit()
    conn.close()


def test_writer_connection(tmp: Path) -> None:
    conn = _connect_writer(tmp / "library.db")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000, "应设 busy_timeout=5000"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        # WAL + busy_timeout 不常驻：用完即 close（短连接方案的核心）
    finally:
        conn.close()


def test_apply_ucs_relabel(tmp: Path) -> None:
    _make_lib(tmp)
    catid_map = load_catid_map(PROJECT / "data-test" / "ucs")
    assert "GUNShotg" in catid_map, "catid_map 应覆盖本测试用的分类"

    conn = db.connect(tmp / "library.db")
    f1_row = conn.execute("SELECT id FROM files WHERE filename='gunshot.wav'").fetchone()
    file_id = int(f1_row["id"])

    summary = apply_ucs_relabel(conn, catid_map, file_id, "AIRBlow")
    assert summary["catid"] == "AIRBlow" and summary["title"], summary

    # ucs_labels 只剩 manual 一条（旧自动 AIRShock 已删）
    rows = conn.execute(
        "SELECT catid, source, confidence FROM ucs_labels WHERE file_id=?",
        (file_id,),
    ).fetchall()
    assert [(r["catid"], r["source"], r["confidence"]) for r in rows] == [
        ("AIRBlow", "manual", 1.0)
    ], f"人工标签应替换全部自动分类：{[dict(r) for r in rows]}"

    # 标签族：旧自动 ucs:* 删除，manual 为 auto=0
    tags = {r["tag"]: r["auto"] for r in conn.execute(
        "SELECT tag, auto FROM tags WHERE file_id=? AND tag LIKE 'ucs:%'", (file_id,)
    ).fetchall()}
    assert tags.get("ucs:AIRBlow") == 0, tags
    assert all(v == 0 for v in tags.values()), "人工改标后不应残留 auto=1 的 ucs 标签"
    assert "boom" in [r["tag"] for r in conn.execute(
        "SELECT tag FROM tags WHERE file_id=?", (file_id,)
    ).fetchall()], "非 ucs 标签应保留"

    # FTS 已刷新：可经 files_fts 检索到 manual 标签
    ftags = conn.execute(
        "SELECT tags FROM files_fts WHERE rowid=?", (file_id,)
    ).fetchone()["tags"]
    assert "ucs:AIRBlow" in (ftags or ""), f"FTS 应含 manual 标签：{ftags}"
    conn.close()


def test_catalog_lists() -> None:
    ucs_dir = PROJECT / "data-test" / "ucs"
    cmap = load_catid_map(ucs_dir)
    assert len(cmap) == 753, f"应 753 类，实际 {len(cmap)}"
    flat = flat_catalog_list(ucs_dir)
    assert len(flat) == 753
    first = flat[0]
    for key in ("catid", "category", "subcategory", "category_zh", "subcategory_zh", "title"):
        assert key in first, f"扁平列表缺字段 {key}"
    # 中文侧存在性：任一含中文名的条目 title 应带中文
    any_zh = any(it.get("category_zh") or it.get("subcategory_zh") for it in flat)
    assert any_zh, "753 类应至少含一条中文（中文 TSV 已合并）"
    # 显示名与 catid 索引一致
    assert flat[0]["title"] == _title_like(cmap, flat[0])
    # 语料缺失应安全返回空
    assert load_catid_map(PROJECT / "no-such-dir") == {}
    assert flat_catalog_list(PROJECT / "no-such-dir") == []


def _title_like(cmap: dict, m: dict) -> str:
    zh = m.get("category_zh") or m.get("category", "")
    sub = m.get("subcategory_zh") or m.get("subcategory", "")
    return f"{zh}/{sub}" if zh else f"{m.get('category', '')}/{sub}"


def test_import_favorites() -> None:
    tmp = Path(tempfile.mkdtemp()) / "state.json"
    store = UserDataStore(tmp)
    store.toggle_favorite("c:/keep.wav", "keep.wav", 9)

    # 导出三种格式 → 各自导入到干净的库，均应解析出 2 条新收藏
    outdir = Path(tempfile.mkdtemp()) / "exp"
    store2 = UserDataStore(Path(tempfile.mkdtemp()) / "s2.json")
    store2.toggle_favorite("d:/alphabet/1.wav", "1.wav", 1)
    store2.toggle_favorite("d:/alphabet/铃铛.wav", "铃铛.wav", 2)
    for fmt in ("md", "csv", "m3u"):
        dest = store2.export_favorites(outdir, fmt)
        fresh = UserDataStore(Path(tempfile.mkdtemp()) / "f.json")
        fresh.toggle_favorite("c:/keep.wav", "keep.wav", 9)
        n = fresh.import_favorites(dest)
        assert n == 2, f"{fmt} 应导入 2 条新收藏，实际 {n}"
        assert len(fresh.favorites) == 3
        assert fresh.favorites[0]["path"] == "d:/alphabet/铃铛.wav", "最新导入应置顶"
        # 重复导入同一文件：不新增
        assert fresh.import_favorites(dest) == 0, f"{fmt} 重复导入不应新增"

    # 混合导入：md → csv → m3u 累计到一个库，共 2 条（去重正确）
    mine = UserDataStore(Path(tempfile.mkdtemp()) / "m.json")
    for fmt in ("md", "csv", "m3u"):
        mine.import_favorites(store2.export_favorites(outdir, fmt))
    assert len(mine.favorites) == 2, f"混合导入应去重为 2 条，实际 {len(mine.favorites)}"

    # 纯路径列表（txt/回退解析）
    txt = tmp.with_name("plain.txt")
    txt.write_text("# list\nc:/only-one.wav\r\n\nc:/only-one.wav\n", encoding="utf-8")
    n = store.import_favorites(txt)
    assert n == 1, f"纯路径列表应导入 1 条（去重），实际 {n}"

    # 上限裁剪
    for i in range(MAX_FAVORITES + 40):
        p = f"z:/pad/{i}.wav"
        txt = tmp.with_name("pad.txt")
        txt.write_text(p, encoding="utf-8")
        store.import_favorites(txt)
    assert len(store.favorites) == MAX_FAVORITES, f"导入应裁剪到 {MAX_FAVORITES}"

    # 不存在的文件 / 空内容应安全
    try:
        store.import_favorites(tmp.with_name("missing.txt"))
        raise AssertionError("不存在的文件应抛 OSError")
    except OSError:
        pass
    empty = tmp.with_name("empty.txt")
    empty.write_text("", encoding="utf-8")
    assert store.import_favorites(empty) == 0

    print("WRITE+IMPORT OK")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sc-write-test-"))
    test_writer_connection(tmp)
    test_apply_ucs_relabel(tmp)
    test_catalog_lists()
    test_import_favorites()
    print("TEST_WRITE_UCS OK")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())