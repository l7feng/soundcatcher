"""SQLite 元数据层。

索引库（``library.db``）只保存**派生数据**，绝不改动用户的源音频文件，随时可删除重建。

表结构（阶段 1 最小集 + 预留）：

- ``files``      —— 一个源音频文件一行
- ``files_fts``  —— FTS5 全文索引（文件名/路径/标签），支撑关键词检索
- ``tags``       —— 用户手动 + 自动标签
- ``ucs_labels`` —— UCS 分类结果（阶段 1 二期接入）
- ``meta``       —— 库级元信息（schema 版本、嵌入模型标识等）

向量本身不入库，由 faiss 索引文件（``index/vectors.faiss``）承载，两者通过
``files.id`` 对齐。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 3  # v2：files_fts 由 contentless 改常规表；v3：新增 sources 来源登记表

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,   -- 绝对路径
    filename      TEXT NOT NULL,          -- 文件名（含扩展名）
    ext           TEXT,                   -- 小写扩展名（不含点）
    size          INTEGER,                -- 字节
    mtime         REAL,                   -- 文件修改时间（增量索引用）
    duration      REAL,                   -- 秒
    sample_rate   INTEGER,
    channels      INTEGER,
    codec         TEXT,
    format        TEXT,
    embedded      INTEGER DEFAULT 0,      -- 是否已生成嵌入并写入 faiss
    error         TEXT,                   -- 最近一次处理失败的原因
    added_at      REAL,
    updated_at    REAL
);

CREATE INDEX IF NOT EXISTS idx_files_ext  ON files(ext);
CREATE INDEX IF NOT EXISTS idx_files_mtime ON files(mtime);

CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    filename, path, tags,
    tokenize='unicode61'
);

CREATE TABLE IF NOT EXISTS tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    auto    INTEGER DEFAULT 0,            -- 1=自动生成 0=人工
    PRIMARY KEY (file_id, tag)
);

CREATE TABLE IF NOT EXISTS ucs_labels (
    file_id    INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    catid      TEXT NOT NULL,
    confidence REAL,
    source     TEXT,                      -- classifier | mirror | manual
    PRIMARY KEY (file_id, catid)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- B5：来源文件夹登记表。只登记路径（不复制、不改动源文件），
-- 供「音效库 → 来源文件夹」管理界面与批量扫描使用。
CREATE TABLE IF NOT EXISTS sources (
    path      TEXT PRIMARY KEY,   -- 绝对路径（唯一，天然去重）
    added_at  TEXT,               -- 登记时间（本地时间字符串）
    last_scan TEXT                -- 上次扫描时间（空 = 从未扫描）
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """打开（或创建）索引库连接，启用 WAL 与外键。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建表并按版本迁移，写入 schema 版本。"""
    conn.executescript(SCHEMA)
    current = get_meta(conn, "schema_version")
    if current is None:
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    elif int(current) < SCHEMA_VERSION:
        _migrate(conn, int(current), SCHEMA_VERSION)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    conn.commit()


def _migrate(conn: sqlite3.Connection, from_v: int, to_v: int) -> None:
    """逐版本迁移。只做幂等、可重复的增量操作。"""
    if from_v < 2:
        # v1 → v2：files_fts 从 contentless（content=''）改为常规表。
        # contentless 表不支持 DELETE，任何"行已存在"的更新（增量扫描改文件、
        # UCS 标签刷新 FTS）都会炸；常规表自带内容、可 DELETE+INSERT 重写。
        conn.execute("DROP TABLE IF EXISTS files_fts")
        conn.execute(
            "CREATE VIRTUAL TABLE files_fts USING fts5("
            "filename, path, tags, tokenize='unicode61')"
        )
        conn.execute(
            """INSERT INTO files_fts(rowid, filename, path, tags)
               SELECT f.id, f.filename, f.path, COALESCE(
                   (SELECT group_concat(t.tag, ' ') FROM tags t
                     WHERE t.file_id = f.id), '')
               FROM files f"""
        )
    if from_v < 3:
        # v2 → v3：新增 sources 来源登记表（建表在 SCHEMA 里已幂等，这里兜底旧库）。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sources (
                   path      TEXT PRIMARY KEY,
                   added_at  TEXT,
                   last_scan TEXT
               )"""
        )


# ---------------------------------------------------------------------------
# meta
# ---------------------------------------------------------------------------


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------


def get_file_by_path(conn: sqlite3.Connection, path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM files WHERE path=?", (path,)).fetchone()


def upsert_file(
    conn: sqlite3.Connection,
    *,
    path: str,
    filename: str,
    ext: str,
    size: int,
    mtime: float,
    duration: float | None = None,
    sample_rate: int | None = None,
    channels: int | None = None,
    codec: str | None = None,
    fmt: str | None = None,
) -> int:
    """插入或更新一个文件记录，返回 ``file_id``。

    已存在时只更新易变字段（size/mtime/技术元数据），并显式把 ``embedded`` 置 0
    由调用方在嵌入成功后改回 1，避免"改了文件却沿用旧向量"。
    """
    now = time.time()
    row = get_file_by_path(conn, path)
    if row is None:
        cur = conn.execute(
            """INSERT INTO files
               (path, filename, ext, size, mtime, duration, sample_rate, channels,
                codec, format, embedded, added_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,0,?,?)""",
            (path, filename, ext, size, mtime, duration, sample_rate, channels, codec, fmt, now, now),
        )
        file_id = int(cur.lastrowid)
        _fts_upsert(conn, file_id, filename, path, "")
    else:
        file_id = int(row["id"])
        conn.execute(
            """UPDATE files SET size=?, mtime=?, duration=?, sample_rate=?, channels=?,
                   codec=?, format=?, embedded=0, error=NULL, updated_at=?
               WHERE id=?""",
            (size, mtime, duration, sample_rate, channels, codec, fmt, now, file_id),
        )
        _fts_upsert(conn, file_id, filename, path, _tags_text(conn, file_id))
    return file_id


def mark_embedded(conn: sqlite3.Connection, file_id: int, ok: bool, error: str | None = None) -> None:
    conn.execute(
        "UPDATE files SET embedded=?, error=?, updated_at=? WHERE id=?",
        (1 if ok else 0, error, time.time(), file_id),
    )


def _tags_text(conn: sqlite3.Connection, file_id: int) -> str:
    rows = conn.execute("SELECT tag FROM tags WHERE file_id=?", (file_id,)).fetchall()
    return " ".join(r["tag"] for r in rows)


# ---------------------------------------------------------------------------
# FTS5 同步
# ---------------------------------------------------------------------------


def _fts_upsert(conn: sqlite3.Connection, file_id: int, filename: str, path: str, tags: str) -> None:
    conn.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
    conn.execute(
        "INSERT INTO files_fts(rowid, filename, path, tags) VALUES (?,?,?,?)",
        (file_id, filename, path, tags),
    )


def refresh_fts_tags(conn: sqlite3.Connection, file_id: int) -> None:
    row = conn.execute("SELECT filename, path FROM files WHERE id=?", (file_id,)).fetchone()
    if row:
        _fts_upsert(conn, file_id, row["filename"], row["path"], _tags_text(conn, file_id))


# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------


def add_tag(conn: sqlite3.Connection, file_id: int, tag: str, auto: bool = False) -> None:
    conn.execute(
        "INSERT INTO tags(file_id, tag, auto) VALUES(?,?,?) "
        "ON CONFLICT(file_id, tag) DO UPDATE SET auto=MIN(auto, excluded.auto)",
        (file_id, tag, 1 if auto else 0),
    )


def list_tags(conn: sqlite3.Connection, file_id: int) -> list[str]:
    rows = conn.execute("SELECT tag FROM tags WHERE file_id=? ORDER BY tag", (file_id,)).fetchall()
    return [r["tag"] for r in rows]


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    """库统计：总文件数 / 已嵌入 / 失败。"""
    total = conn.execute("SELECT COUNT(*) c FROM files").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) c FROM files WHERE embedded=1").fetchone()["c"]
    failed = conn.execute("SELECT COUNT(*) c FROM files WHERE error IS NOT NULL").fetchone()["c"]
    return {"total": total, "embedded": embedded, "failed": failed}
