"""构建 GUI 开发用测试小库（独立 ``data-test/`` 目录，绝不碰真实 ``data/``）。

GUI 开发/冒烟期间不可对真实索引库写入（坑 11：并发写 SQLite），因此测试库
与真实库隔离：模型与 UCS 语料复用默认 home（只读共享），索引数据落在
``<工程>/data-test/``。GUI 以环境变量 ``SOUNDCATCHER_DATA_HOME`` 指向它运行。

用法::

    python scripts/make_test_lib.py                 # 默认扫 C:\\Windows\\Media（80 个系统音效）
    python scripts/make_test_lib.py "D:\\某目录"     # 指定目录
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from soundcatcher import db  # noqa: E402
from soundcatcher.config import Config  # noqa: E402
from soundcatcher.embedder import ClapEmbedder  # noqa: E402
from soundcatcher.indexer import Indexer, VectorIndex  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_HOME = PROJECT_ROOT / "data-test"

DEFAULT_ROOTS = [r"C:\Windows\Media"]


def main() -> None:
    roots = sys.argv[1:] or DEFAULT_ROOTS
    print(f"[make_test_lib] 扫描目标：{roots}")
    print(f"[make_test_lib] 测试库：{TEST_HOME}")

    cfg = Config.default()
    conn = db.connect(TEST_HOME / "library.db")
    db.init_db(conn)
    embedder = ClapEmbedder(cfg.models_dir)
    index = VectorIndex(TEST_HOME / "index" / "vectors.faiss")
    indexer = Indexer(conn, index, embedder)

    def cb(done: int, total: int, current: str) -> None:
        if done % 25 == 0 or done == total:
            print(f"  {done}/{total}  {Path(current).name[:48]}")

    stats = indexer.scan(roots, progress=cb)
    print(stats.summary())
    if stats.errors:
        for p, e in stats.errors[:5]:
            print(f"  ERR {p} → {e[:100]}")


if __name__ == "__main__":
    main()