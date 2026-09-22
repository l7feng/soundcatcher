"""QML 后端：把检索核心桥接到 Qt 界面。

线程模型（三线程 + UI 主线程）：

.. code-block:: text

    UI 线程（QML）               模型线程（QThread）            波形线程（QThread）
    AppBackend  ←────queued────  LibraryWorker
     QMediaPlayer(播放)  ──┐
     WaveformService  ←────┘（decode_mono48k → 峰值箱 → QML Canvas）

- 所有模型推理（CLAP 双塔 / 翻译桥）与 SQLite 访问只在模型线程；
- 波形解码是 PyAV 密集活，单独一线程，避免与搜索互相阻塞；
- 播放用 QtMultimedia（QMediaPlayer 内部自有线程），UI 线程持有即可。

库打开为**严格只读**：SQLite 以 ``mode=ro`` URI 打开，不执行任何 schema
写入；faiss 索引只读加载。因此 GUI 与另一扫描进程可安全共存。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import (
    Property,
    QAbstractItemModel,
    QModelIndex,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaMetaData

from .. import db
from ..audio import decode_mono48k
from ..config import Config
from ..embedder import ClapEmbedder
from ..indexer import VectorIndex
from ..search import SearchResult, Searcher
from ..translator import OpusTranslator
from .settings import PATH_KEYS, Settings, settings_path
from .userdata import UserDataStore, default_state_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 只读库连接
# ---------------------------------------------------------------------------


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    """以只读模式打开索引库（不建表、不迁移、不写 meta）。

    与扫描进程（写者）并发安全：SQLite WAL 允许多读者 + 单写者。
    """
    if not db_path.exists():
        raise FileNotFoundError(
            f"索引库不存在：{db_path}。请先在命令行运行 soundcatcher scan 建立索引。"
        )
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _data_home() -> Path:
    """数据目录：默认 ``Config.data_dir``，可用 ``SOUNDCATCHER_DATA_HOME`` 覆盖。"""
    return Config.default().data_dir


def _catalog_dir() -> Path:
    """UCS 静态语料目录（753 类字典）：默认 ``Config.catalog_dir``。

    注意：与 ``data/ucs/``（派生原型矩阵）**不是一回事** —— 这里是只读「原料」。
    """
    return Config.default().catalog_dir


def _export_dir() -> Path:
    """收藏夹导出默认目录：``SOUNDCATCHER_EXPORT_DIR`` > Downloads > home。"""
    env = os.environ.get("SOUNDCATCHER_EXPORT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    dl = Path.home() / "Downloads"
    if dl.is_dir():
        return dl
    return Path.home()


def _peaks(wav: np.ndarray, bins: int = 600) -> list[float]:
    """波形 → ``bins`` 个 0~1 峰值箱（QML Canvas 绘制复用）。"""
    a = np.abs(wav).astype(np.float32)
    n = a.size
    if n == 0:
        return [0.0] * bins
    if n < bins * 2:
        peak = float(a.max())
        return [peak] * bins
    edges = np.linspace(0, n, bins + 1).astype(np.int64)
    seg_max = np.maximum.reduceat(a, edges[:-1])
    m = float(seg_max.max()) or 1.0
    return [(float(v) / m) for v in seg_max]


def _pid_alive(pid: int) -> bool:
    """Windows/Unix 通用进程存活探测（``os.kill(pid, 0)`` 只发信号不杀进程）。"""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _result_to_dict(r: SearchResult) -> dict:
    """SearchResult → QML 友好 dict。"""
    ucs_tags = [t for t in r.tags if t.startswith("ucs:") and not t.startswith("ucs:S")]
    other_tags = [t for t in r.tags if not t.startswith("ucs:")]
    return {
        "fileId": r.file_id,
        "path": r.path,
        "filename": r.filename,
        "parent": Path(r.path).parent.name or Path(r.path).parent.as_posix(),
        "duration": r.duration,
        "durationStr": r.duration_str,
        "score": r.score,
        "source": r.source,
        "tags": r.tags,
        "ucsTags": ucs_tags[:3],
        "otherTags": other_tags[:3],
    }


# ---------------------------------------------------------------------------
# UCS 人工打标：对库做一次性的小写操作（GUI 主体仍只读，写走独立短连接）
#
# 安全写锁方案（迭代三，2026-09-18 定案）：
# - 常驻 UI 会话仍严格只读（``_connect_readonly``，mode=ro），绝不在其上执行写；
# - 一切写（人工 UCS 改标）用**新建的短连接** ``_connect_writer``：WAL 本就允许
#   单写者+多读者；busy_timeout=5s 让与扫描子进程的写锁竞争不抛
#   ``database is locked``——SQLite 自动排队，而非两个 GUI 常驻连接互相死等；
# - 写完立刻 commit + close，**不常驻**，锁面最小化；WAL 下读者无需退出即可
#   看到已提交的新数据（刷新树/结果即得）；
# - 数据层复用 ``apply_ucs_relabel``（删旧自动 label → 写 manual → 重建 ucs:* 标签族
#   → 刷 FTS），仅业务入口在 GUI 侧短连接内调用一次。
# ---------------------------------------------------------------------------


def _connect_writer(db_path: str | Path) -> sqlite3.Connection:
    """新建可写短连接（WAL + FK + synchronous=NORMAL + busy_timeout）。"""
    conn = db.connect(db_path)                       # 已设 WAL / FK / NORMAL
    conn.execute("PRAGMA busy_timeout=5000")          # 与扫描子进程竞争时排队等待
    return conn


def _write_with_retry(fn, attempts: int = 3):
    """对短连接写操作做极简重试：锁竞争偶发时等 0.2s 再试，最多 3 次。"""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last = exc
            if "locked" in str(exc).lower() and i < attempts - 1:
                time.sleep(0.2)
                continue
            raise
    raise last  # pragma: no cover  # noqa: B904


def load_catid_map(ucs_dir: str | Path) -> dict[str, dict]:
    """读 ``ucs/catalog.json`` → ``catid → {category, subcategory, *_zh}``。

    供人工改标显示名与校验用；语料缺失/异常时返回空字典（改标降级为只写 CatID）。
    """
    meta_path = Path(ucs_dir) / "catalog.json"
    if not meta_path.exists():
        return {}
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            str(m.get("catid", "")).strip(): {
                "category": m.get("category", ""),
                "subcategory": m.get("subcategory", ""),
                "category_zh": m.get("category_zh", ""),
                "subcategory_zh": m.get("subcategory_zh", ""),
            }
            for m in meta.get("entries", []) if m.get("catid")
        }
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("catalog.json 读取失败：%s", exc)
        return {}


def flat_catalog_list(ucs_dir: str | Path) -> list[dict]:
    """扁平 753 类列表（分类选择 Popup 用，含搜索过滤所需字段）。"""
    entries = flat_catalog_entries(ucs_dir)
    return [
        {
            "catid": m["catid"],
            "category": m.get("category", ""),
            "subcategory": m.get("subcategory", ""),
            "category_zh": m.get("category_zh", ""),
            "subcategory_zh": m.get("subcategory_zh", ""),
            "title": _title_for(m["catid"], {m["catid"]: m}),
        }
        for m in entries
    ]


def flat_catalog_entries(ucs_dir: str | Path) -> list[dict]:
    """读 ``ucs/catalog.json`` 原样 entries 列表；缺失/异常返回 []。"""
    meta_path = Path(ucs_dir) / "catalog.json"
    if not meta_path.exists():
        logger.warning("UCS 语料缺失：%s（先运行 soundcatcher ucs init）", meta_path)
        return []
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return [dict(m) for m in meta.get("entries", []) if m.get("catid")]
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("catalog.json 读取失败：%s", exc)
        return []


def _title_for(catid: str, catid_map: dict[str, dict]) -> str:
    """CatID → 显示名（英文兜底）。"""
    m = catid_map.get(catid)
    if not m:
        return catid
    zh = (m.get("category_zh") or "") or m.get("category", "")
    sub = (m.get("subcategory_zh") or "") or m.get("subcategory", "")
    return f"{zh}/{sub}" if zh else f"{m.get('category', '')}/{sub}"


def apply_ucs_relabel(
    conn: sqlite3.Connection, catid_map: dict[str, dict], file_id: int, catid: str
) -> dict:
    """把一个文件的人工 UCS 分类写回（source=manual，置信度 1.0）。

    语义：人工标签**替换**该文件的全部自动分类——删掉旧 ucs_labels 行，
    重建 ``ucs:*`` 标签族（人工 auto=0），刷新 FTS。返回结果摘要。

    ``catid_map``：``catid → {category, subcategory, category_zh, subcategory_zh}``
    （可由 backend 从 catalog.json 构建；不传入则为 0 遍历式小字典）。
    """
    old = conn.execute(
        "SELECT catid FROM ucs_labels WHERE file_id=?", (file_id,)
    ).fetchall()
    conn.execute("DELETE FROM ucs_labels WHERE file_id=?", (file_id,))
    conn.execute(
        """INSERT INTO ucs_labels(file_id, catid, confidence, source)
           VALUES (?,?,?,?)""",
        (file_id, catid, 1.0, "manual"),
    )

    # 删自动 ucs 标签，重建人工 ucs 标签族（ucs:CatID + 中文/英文显示名 + 同义词）
    conn.execute(
        "DELETE FROM tags WHERE file_id=? AND tag LIKE 'ucs:%' AND auto=1",
        (file_id,),
    )
    db.add_tag(conn, file_id, f"ucs:{catid}", auto=False)
    m = catid_map.get(catid)
    if m:
        title_en = f"{m.get('category', '')}/{m.get('subcategory', '')}"
        title_zh = _title_for(catid, catid_map)
        if title_zh != title_en:
            db.add_tag(conn, file_id, f"ucs:{title_zh}", auto=False)
    db.refresh_fts_tags(conn, file_id)
    conn.commit()
    return {
        "file_id": file_id,
        "catid": catid,
        "title": _title_for(catid, catid_map),
        "removed": [r["catid"] for r in old] if old else [],
    }


# ---------------------------------------------------------------------------
# UCS 浏览树：纯数据节点 + QAbstractItemModel（QML TreeView 用）
# ---------------------------------------------------------------------------


class _UcsNode:
    """UCS 树节点（纯 Python 数据，可在工作线程构造、经信号传递）。"""

    __slots__ = ("catid", "title", "count", "depth", "children", "parent", "row")

    def __init__(self, catid: str, title: str, count: int, depth: int):
        self.catid = catid          # 叶子=UCS CatID；分类节点=""
        self.title = title          # 显示名（含中文侧）
        self.count = count          # 文件计数（父=子级累计）
        self.depth = depth          # 0=Category 1=叶子（753 子类）
        self.children: list[_UcsNode] = []
        self.parent: _UcsNode | None = None
        self.row = 0


def _build_ucs_tree(conn: sqlite3.Connection, ucs_dir: Path) -> list[_UcsNode]:
    """从 ``ucs/catalog.json`` + ``ucs_labels`` 计数构树（两层级联）。

    返回根节点列表（82 个 Category）；无语料时返回空列表。
    """
    meta_path = Path(ucs_dir) / "catalog.json"
    if not meta_path.exists():
        logger.warning("UCS 语料缺失：%s（先运行 soundcatcher ucs init）", meta_path)
        return []
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    counts: dict[str, int] = {}
    try:
        rows = conn.execute(
            "SELECT catid, COUNT(*) AS n FROM ucs_labels GROUP BY catid"
        ).fetchall()
        counts = {str(r["catid"]): int(r["n"]) for r in rows}
    except sqlite3.Error as exc:  # 只读库异常时计数归零，不让整树挂掉
        logger.warning("ucs_labels 计数失败：%s", exc)

    roots: dict[str, _UcsNode] = {}
    for m in meta.get("entries", []):
        cat = str(m.get("category", "")).strip()
        if not cat:
            continue
        root = roots.get(cat)
        if root is None:
            zh = (m.get("category_zh") or "").strip()
            root = _UcsNode("", f"{cat}{'（' + zh + '）' if zh else ''}", 0, 0)
            roots[cat] = root
        sub = str(m.get("subcategory", "")).strip()
        sub_zh = (m.get("subcategory_zh") or "").strip()
        leaf = _UcsNode(
            str(m.get("catid", "")).strip(),
            f"{sub}{'（' + sub_zh + '）' if sub_zh else ''}",
            counts.get(str(m.get("catid", "")), 0),
            1,
        )
        root.children.append(leaf)
        root.count += leaf.count

    ordered = sorted(roots.values(), key=lambda n: n.title)
    return ordered


class UcsTreeModel(QAbstractItemModel):
    """UCS 分类浏览树模型（Category → 753 子类），供 QML TreeView 使用。"""

    TitleRole = Qt.ItemDataRole.UserRole + 1
    CountRole = Qt.ItemDataRole.UserRole + 2
    CatIdRole = Qt.ItemDataRole.UserRole + 3
    LeafRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self, roots: list[_UcsNode], parent: QObject | None = None):
        super().__init__(parent)
        self._roots = roots or []
        self._link()

    def _link(self) -> None:
        def walk(n: _UcsNode) -> None:
            for i, ch in enumerate(n.children):
                ch.parent, ch.row = n, i
                walk(ch)
        for i, r in enumerate(self._roots):
            r.parent, r.row = None, i
            walk(r)

    # -- QAbstractItemModel 纯虚实现 --------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._roots)
        node: _UcsNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 1

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if column != 0 or row < 0:
            return QModelIndex()
        if not parent.isValid():
            if row >= len(self._roots):
                return QModelIndex()
            node = self._roots[row]
        else:
            p = parent.internalPointer()
            if row >= len(p.children):
                return QModelIndex()
            node = p.children[row]
        return self.createIndex(row, 0, node)

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        p: _UcsNode | None = index.internalPointer().parent
        if p is None:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        if not parent.isValid():
            return bool(self._roots)
        return bool(parent.internalPointer().children)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: _UcsNode = index.internalPointer()
        if role == self.TitleRole:
            return node.title
        if role == self.CountRole:
            return node.count
        if role == self.CatIdRole:
            return node.catid
        if role == self.LeafRole:
            return not bool(node.children)
        return None

    def roleNames(self) -> dict:
        return {
            self.TitleRole: b"tit",
            self.CountRole: b"cnt",
            self.CatIdRole: b"catid",
            self.LeafRole: b"isleaf",
        }


# ---------------------------------------------------------------------------
# 模型线程：加载与检索
# ---------------------------------------------------------------------------


class LibraryWorker(QObject):
    """持有只读库 + 嵌入器 + 检索器的常驻工作对象（moveToThread 到模型线程）。"""

    ready = Signal(bool, str)          # (ok, message)
    searchFinished = Signal(list)      # list[dict]
    similarFinished = Signal(list)
    searchFailed = Signal(str)
    statsUpdated = Signal(int, int, int)  # (total, embedded, failed)
    translationNote = Signal(str)      # 中文查询的英译提示
    queryLatency = Signal(float)       # 本次查询耗时（秒，延迟观测用）
    ucsTreeReady = Signal(list)        # list[_UcsNode]（根节点）
    browseFinished = Signal(list)      # list[dict]（UCS 浏览结果）

    def __init__(self, models_dir: Path, data_home: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.models_dir = Path(models_dir)
        self.db_path = Path(data_home) / "library.db"
        self.index_path = Path(data_home) / "index" / "vectors.faiss"
        self.ucs_dir = Path(data_home) / "ucs"
        # UCS 静态语料（753 类字典）在 catalog/，与 data/ucs/ 的派生矩阵是两回事
        self.catalog_dir = _catalog_dir()
        self.conn: sqlite3.Connection | None = None
        self.index: VectorIndex | None = None
        self.embedder: ClapEmbedder | None = None
        self.searcher: Searcher | None = None

    # -- 打开 --------------------------------------------------------------

    @Slot()
    def open(self) -> None:
        try:
            t0 = time.perf_counter()
            self.conn = _connect_readonly(self.db_path)
            self.index = VectorIndex(self.index_path)  # 不存在则为空索引（只读，不落盘）
            self.embedder = ClapEmbedder(self.models_dir)
            self.searcher = Searcher(
                self.conn, self.index, self.embedder, translator_factory=self._translator_factory()
            )
            n = db.stats(self.conn)
            load_s = time.perf_counter() - t0
            total, embedded, failed = n["total"], n["embedded"], n["failed"]
            self._emit_stats()
            logger.info("库打开：%d 文件 / 已嵌入 %d / 失败 %d（%.1fs）", total, embedded, failed, load_s)
            self.ready.emit(True, f"库就绪：{total} 个文件，已嵌入 {embedded}（加载 {load_s:.1f}s）")
        except Exception as exc:  # noqa: BLE001
            logger.exception("库打开失败")
            self.ready.emit(False, str(exc))
        finally:
            # UCS 树与库无关，语料缺失也不应阻塞主流程
            self.loadUcsTree()

    def _translator_factory(self):
        model_dir = self.models_dir / "opus-mt-zh-en"
        if not (model_dir / "onnx_encoder_model.onnx").exists():
            return None

        def build() -> OpusTranslator:
            return OpusTranslator(model_dir)

        return build

    # -- 查询 --------------------------------------------------------------

    @Slot(str, str, int)
    def search(self, text: str, mode: str, limit: int) -> None:
        if self.searcher is None:
            self.searchFailed.emit("检索器未就绪")
            return
        try:
            t0 = time.perf_counter()
            results = self.searcher.search(text, mode=mode, limit=limit)
            latency = time.perf_counter() - t0
            items = [_result_to_dict(r) for r in results]
            self.searchFinished.emit(items)
            self.queryLatency.emit(latency)
            if self.searcher.last_translation:
                self.translationNote.emit(
                    f"Chinese（中文）→ {self.searcher.last_translation}"
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("检索失败")
            self.searchFailed.emit(str(exc))

    @Slot(str, int)
    def similar(self, audio_path: str, limit: int) -> None:
        if self.searcher is None:
            self.searchFailed.emit("检索器未就绪")
            return
        try:
            t0 = time.perf_counter()
            results = self.searcher.search_similar(audio_path, limit=limit)
            latency = time.perf_counter() - t0
            items = [_result_to_dict(r) for r in results]
            self.similarFinished.emit(items)
            self.queryLatency.emit(latency)
        except Exception as exc:  # noqa: BLE001
            logger.exception("以声搜声失败")
            self.searchFailed.emit(f"以声搜声失败：{exc}")

    @Slot()
    def refreshStats(self) -> None:
        self._emit_stats()

    def _emit_stats(self) -> None:
        if self.conn is None:
            return
        n = db.stats(self.conn)
        self.statsUpdated.emit(n["total"], n["embedded"], n["failed"])

    # -- UCS 浏览 ----------------------------------------------------------

    @Slot()
    def loadUcsTree(self) -> None:
        """读 ``data/ucs/catalog.json`` + 计数 → 构树 → 发根节点列表（UI 线程组模型）。

        注意：读的是 **``data/ucs/catalog.json``（派生元数据）**，不是
        ``catalog/``（静态 CSV/TSV 原料）。两者同名但不同物 ——
        ``catalog/`` 供 ``ucs init`` 生成原型矩阵用，GUI 不直接读它。
        """
        if self.conn is None:
            self.ucsTreeReady.emit([])
            return
        try:
            roots = _build_ucs_tree(self.conn, self.ucs_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("UCS 树构建失败：%s", exc)
            roots = []
        self.ucsTreeReady.emit(roots)

    @Slot(str, int)
    def browseUcs(self, catid: str, limit: int) -> None:
        """按 UCS CatID 浏览：``ucs_labels`` 按置信度取 top-K（结果仍可试听）。"""
        if self.conn is None or self.searcher is None:
            self.searchFailed.emit("检索器未就绪")
            return
        try:
            rows = self.conn.execute(
                """SELECT file_id, confidence FROM ucs_labels
                   WHERE catid=? ORDER BY confidence DESC LIMIT ?""",
                (catid, limit),
            ).fetchall()
            items: list[dict] = []
            for r in rows:
                sr = self.searcher._to_result(
                    int(r["file_id"]), float(r["confidence"] or 0.0), "ucs"
                )
                if sr is not None:
                    items.append(_result_to_dict(sr))
            self.browseFinished.emit(items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("UCS 浏览失败")
            self.searchFailed.emit(f"UCS 浏览失败：{exc}")


# ---------------------------------------------------------------------------
# 波形线程：懒加载峰值
# ---------------------------------------------------------------------------


class WaveformService(QObject):
    """在独立线程解码音频 → 峰值箱，供 QML Canvas 绘制。"""

    waveformReady = Signal(int, list)      # (file_id, peaks)
    waveformFailed = Signal(int, str)
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._busy = False
        self._thread: QThread | None = None

    @Slot(int, str)
    def load(self, file_id: int, path: str) -> None:
        try:
            self.busyChanged.emit(True)
            wav = decode_mono48k(path, max_seconds=120.0)
            peaks = _peaks(wav, bins=600)
            self.waveformReady.emit(file_id, peaks)
        except Exception as exc:  # noqa: BLE001
            logger.warning("波形解码失败：%s", exc)
            self.waveformFailed.emit(file_id, str(exc))
        finally:
            self.busyChanged.emit(False)


# ---------------------------------------------------------------------------
# AppBackend：QML 可见外观
# ---------------------------------------------------------------------------


class AppBackend(QObject):
    """GUI 的对外门面：属性 + 槽（QML 直接调用）+ 信号（QML 绑定）。"""

    # -- 信号（QML 侧绑定） ------------------------------------------------
    ready = Signal(bool, str)
    searchFinished = Signal(list)
    searchFailed = Signal(str)
    translationNote = Signal(str)
    statsChanged = Signal(int, int, int)
    queryLatency = Signal(float)
    searchingChanged = Signal(bool)
    waveformReady = Signal(int, list)
    currentFileChanged = Signal()
    playStateChanged = Signal(str)       # playing | paused | stopped
    positionChanged = Signal("qlonglong")  # ms（QMediaPlayer 为 qint64，须同型直连）
    durationChanged = Signal("qlonglong")  # ms
    ucsTreeChanged = Signal()
    browseFinished = Signal(list)
    favoritesChanged = Signal()
    savedSearchesChanged = Signal()
    sourcesChanged = Signal()
    scanStateChanged = Signal()
    settingsChanged = Signal()          # 主题 / 语言 / 侧栏宽度 / 路径偏好变化
    restartRequired = Signal(str)       # 路径迁移完成，需重启（携带提示文案）

    # 内部请求信号：跨线程排队到模型线程（直接调用方法不会排队，会跑在 UI 线程）
    _searchReq = Signal(str, str, int)
    _similarReq = Signal(str, int)
    _statsReq = Signal()
    _ucsTreeReq = Signal()
    _browseUcsReq = Signal(str, int)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        cfg = Config.default()
        models_dir = cfg.models_dir
        data_home = _data_home()

        self._searching = False
        self._current_file: dict | None = None
        self._current_waveform: list[float] | None = None
        self._ucs_model = UcsTreeModel([])
        self._user = UserDataStore(default_state_path())
        # 应用偏好（主题 / 语言 / 侧栏宽度 / 路径偏好）
        self._settings = Settings(settings_path())

        # 写路径（人工改标）：短连接 + 只读会话不动
        self._db_path = Path(data_home) / "library.db"
        self._ucs_dir = Path(data_home) / "ucs"
        self._catid_map: dict[str, dict] | None = None
        self._catalog_list: list[dict] | None = None

        # 播放器（UI 线程持有；QtMultimedia 内部自管线程）
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.positionChanged.connect(self.positionChanged)
        self.player.durationChanged.connect(self.durationChanged)
        self.player.playbackStateChanged.connect(self._on_playback_state)
        self.audio_output.volumeChanged.connect(self._on_volume)

        # 模型线程
        self._model_thread = QThread(self)
        self._worker = LibraryWorker(models_dir, data_home)
        self._worker.moveToThread(self._model_thread)
        self._worker.ready.connect(self.ready)
        self._worker.searchFinished.connect(self._on_search_finished)
        self._worker.similarFinished.connect(self._on_search_finished)
        self._worker.searchFailed.connect(self.searchFailed)
        self._worker.statsUpdated.connect(self.statsChanged)
        self._worker.translationNote.connect(self.translationNote)
        self._worker.queryLatency.connect(self.queryLatency)
        self._worker.ucsTreeReady.connect(self._on_ucs_tree_data)
        self._worker.browseFinished.connect(self._on_browse_finished)
        self._searchReq.connect(self._worker.search)
        self._similarReq.connect(self._worker.similar)
        self._statsReq.connect(self._worker.refreshStats)
        self._ucsTreeReq.connect(self._worker.loadUcsTree)
        self._browseUcsReq.connect(self._worker.browseUcs)
        self._model_thread.started.connect(self._worker.open)
        self._model_thread.start()

        # 波形线程
        self._wave_thread = QThread(self)
        self._wave_service = WaveformService()
        self._wave_service.moveToThread(self._wave_thread)
        self._wave_service.waveformReady.connect(self._on_waveform_ready)
        self._wave_service.waveformFailed.connect(self._on_waveform_failed)
        self._wave_thread.start()

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self.refreshStats)
        self._stats_timer.start(15_000)  # 每 15s 轮询一次库统计（扫描进行时会增长）

        # 后台扫描子进程（独立写者；GUI 保持只读与扫描并存）
        self._scan_data_home = Path(data_home)
        self._scan_log = self._scan_data_home / "gui_scan.log"
        self._scan_pid = self._scan_data_home / "gui_scan.pid"
        self._scan_proc: subprocess.Popen | None = None
        self._scan_state = "idle"        # idle | running | done | failed
        self._scan_message = ""
        self._scan_target = ""           # 目标目录名（进度前缀用）
        self._scan_stopping = False      # 手动停止后终态显示"已停止"而非"异常"
        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._tick_scan)
        self._scan_timer.start(2000)     # 2s 探测子进程退出

    # -- 属性 --------------------------------------------------------------

    @property
    def searching(self) -> bool:
        return self._searching

    # -- 应用偏好（主题 / 语言 / 侧栏宽度 / 路径）---------------------------

    def getTheme(self) -> str:
        return self._settings.theme

    @Slot(str, result=str)
    def setTheme(self, mode: str) -> str:
        """切换主题（light | dark | system）并持久化；返回给状态栏的提示。"""
        if mode not in ("light", "dark", "system"):
            return f"未知主题：{mode}"
        self._settings.theme = mode
        self._settings.save()
        self.settingsChanged.emit()
        return mode

    theme = Property(str, getTheme, notify=settingsChanged)

    def getLanguage(self) -> str:
        return self._settings.language

    @Slot(str, result=str)
    def setLanguage(self, lang: str) -> str:
        """切换界面语言（zh | en）并持久化。"""
        if lang not in ("zh", "en"):
            return f"未知语言：{lang}"
        self._settings.language = lang
        self._settings.save()
        self.settingsChanged.emit()
        return lang

    language = Property(str, getLanguage, notify=settingsChanged)

    def getSidebarWidth(self) -> int:
        return self._settings.sidebar_width

    @Slot(int)
    def setSidebarWidth(self, w: int) -> None:
        """记住用户拖拽后的侧栏宽度（Qt 不自动持久化布局）。"""
        from .settings import MAX_SIDEBAR, MIN_SIDEBAR
        w = max(MIN_SIDEBAR, min(MAX_SIDEBAR, int(w)))
        if w != self._settings.sidebar_width:
            self._settings.sidebar_width = w
            self._settings.save()

    sidebarWidth = Property(int, getSidebarWidth, setSidebarWidth, notify=settingsChanged)

    # -- B3：UCS 树可见性 + 侧栏页签记忆 ------------------------------------

    @Slot(result=bool)
    def getShowUcsTree(self) -> bool:
        return self._settings.show_ucs_tree

    @Slot(bool)
    def setShowUcsTree(self, on: bool) -> None:
        on = bool(on)
        if on != self._settings.show_ucs_tree:
            self._settings.show_ucs_tree = on
            self._settings.save()
            self.settingsChanged.emit()

    @Slot(result=int)
    def getLastSideTab(self) -> int:
        return self._settings.last_side_tab

    @Slot(int)
    def setLastSideTab(self, idx: int) -> None:
        idx = max(0, min(2, int(idx)))
        if idx != self._settings.last_side_tab:
            self._settings.last_side_tab = idx
            self._settings.save()

    @Slot(result="QVariant")
    def pathInfo(self) -> list[dict]:
        """5 条可改路径的当前生效值 + 是否被环境变量/设置覆盖（设置面板用）。"""
        eff = self._settings.effective_paths()
        out: list[dict] = []
        for key, desc in PATH_KEYS.items():
            overridden = bool(self._settings.paths.get(key))
            env_forced = self._path_env_forced(key)
            out.append({
                "key": key,
                "desc": desc,
                "path": eff[key],
                "custom": overridden,
                "envForced": env_forced,
            })
        return out

    @staticmethod
    def _path_env_forced(key: str) -> bool:
        """该路径是否由**外部**设置的（settings.json 之外的）环境变量强制。

        用于设置面板警示：环境变量优先级最高，此时 UI 改了也不生效。
        """
        mapping = {
            "dataHome": "SOUNDCATCHER_DATA_HOME",
            "stateDir": "SOUNDCATCHER_APPDATA",
            "modelsDir": "SOUNDCATCHER_MODELS",
            "catalogDir": "SOUNDCATCHER_CATALOG",
            "exportDir": "SOUNDCATCHER_EXPORT_DIR",
        }
        return bool(os.environ.get(mapping.get(key, "")))

    @Slot(result=str)
    def appVersion(self) -> str:
        """应用版本（关于对话框用）；读不到就回退占位符，不抛错。"""
        try:
            from .. import __version__ as v
            return str(v)
        except Exception:  # noqa: BLE001
            return "0.1.0"

    @Slot(result=str)
    def settingsFilePath(self) -> str:
        return str(self._settings.path)

    @Slot(str, str, bool, result="QVariant")
    def setPath(self, key: str, new_path: str, migrate: bool = True) -> dict:
        """改一条可改路径，可选把旧数据搬过去。

        流程（用户原话：「更改后直接把之前的移过去，然后是不是需要重启软件？
        然后把旧的删除」）：
        1. 校验 key；``new_path`` 空 = 恢复默认（只改配置，不搬）
        2. 环境变量已强制该项 → 拒绝（改了也不生效，直接告知）
        3. 需要迁移且旧目录有内容 → ``migrate_path(mode="move")``
        4. 写 settings.json（**不删旧目录**，只留空壳，让用户自己确认后处理）
        5. 发 ``restartRequired``（路径在进程启动早期被 config 捕获，热改不生效）

        返回 ``{"ok", "msg", "needRestart", "migrated", "key"}``。
        """
        from .settings import PATH_KEYS, migrate_path

        if key not in PATH_KEYS:
            return {"ok": False, "msg": f"未知路径项：{key}", "needRestart": False,
                    "migrated": 0, "key": key}
        if self._path_env_forced(key):
            return {"ok": False,
                    "msg": "该项被环境变量强制（SOUNDCATCHER_*），设置面板改了不生效。"
                           "请先清除对应环境变量。",
                    "needRestart": False, "migrated": 0, "key": key}

        new_path = (new_path or "").strip()
        old_eff = self._settings.effective_paths().get(key, "")
        migrated = 0
        note = ""

        if not new_path:
            # 恢复默认
            self._settings.paths[key] = None
            self._settings.save()
            self.settingsChanged.emit()
            return {"ok": True, "msg": f"已恢复默认：{old_eff}", "needRestart": True,
                    "migrated": 0, "key": key}

        np = Path(new_path).expanduser()
        if migrate and old_eff and Path(old_eff) != np:
            res = migrate_path(key, old_eff, np, mode="move")
            if not res.ok:
                return {"ok": False, "msg": res.summary(), "needRestart": False,
                        "migrated": 0, "key": key}
            migrated = res.moved
            note = res.summary()

        self._settings.paths[key] = str(np)
        self._settings.save()
        self.settingsChanged.emit()
        msg = note or f"路径已更新：{np}"
        self.restartRequired.emit(msg)
        return {"ok": True, "msg": msg, "needRestart": True, "migrated": migrated, "key": key}

    @Slot(str, str, result="QVariant")
    def previewPathMove(self, key: str, new_path: str) -> dict:
        """迁移前预演：告诉 UI 会搬多少条目、有没有拦路问题（不改任何东西）。"""
        from .settings import PATH_KEYS, migrate_path

        if key not in PATH_KEYS:
            return {"ok": False, "msg": f"未知路径项：{key}", "count": 0}
        old_eff = self._settings.effective_paths().get(key, "")
        np = (new_path or "").strip()
        if not np:
            return {"ok": True, "msg": "将恢复为默认路径（无需迁移）", "count": 0}
        res = migrate_path(key, old_eff, Path(np).expanduser(), mode="move", dry_run=True)
        return {"ok": res.ok, "msg": res.summary() if not res.ok else
                f"将移动 {res.moved} 个条目：{old_eff} → {np}",
                "count": res.moved, "old": old_eff, "new": np}

    @Slot(str, result=bool)
    def isDir(self, path: str) -> bool:
        """拖放分派用：判断拖入的 url 指向目录还是文件（B2）。

        路径可能来自 QML 的 url 转换，可能带尾部分隔符或为空 → 统一容错为 False。
        """
        if not path:
            return False
        try:
            return Path(path).is_dir()
        except OSError:
            return False

    @Slot(str, result=str)
    def openFolder(self, path: str) -> str:
        """在资源管理器里打开目录（菜单「打开数据目录」等用）。"""
        p = Path(path) if path else Path.home()
        if not p.exists():
            return f"目录不存在：{p}"
        try:
            if os.name == "nt":
                os.startfile(str(p))  # noqa: S606  (Windows 专用，无更安全替代)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except OSError as exc:
            return f"打开失败：{exc}"
        return f"已打开：{p}"

    @Slot(result=str)
    def openDataFolder(self) -> str:
        return self.openFolder(str(_data_home().parent))

    @Slot(result=str)
    def openExportFolder(self) -> str:
        return self.openFolder(str(_export_dir()))

    @Slot(bool)
    def setSearching(self, on: bool) -> None:
        if on != self._searching:
            self._searching = on
            self.searchingChanged.emit(on)

    def getSearching(self) -> bool:
        return self._searching

    # 给 Qt 属性起名 "searching"。
    # **坑**：不能写成 `searching = Property(...)` —— 上面（第 746 行附近）已有一个
    # 同名 `@property`，后写的会覆盖它，于是元对象里注册出来的名字变成变量名
    # `searching_prop`。QML 里 `backend.searching` 就永远取到 undefined（静默失效：
    # 搜索忙碌指示器不转、状态文案不切，且只在加载时报一条 "Unable to assign
    # [undefined] to bool"）。此属性覆盖后，C++ 侧 getter/setter 都走上面的
    # getSearching/setSearching，行为不变。
    searching = Property(bool, getSearching, setSearching, notify=searchingChanged)

    @property
    def currentFile(self) -> dict | None:
        return self._current_file

    def getCurrentFile(self) -> dict | None:
        return self._current_file

    # 同 searching 的坑：这个类上面已有 `currentFile` 的 @property，
    # 属性名必须显式写成 "currentFile" 才不会被顶成 `currentFileProp`。
    currentFile = Property("QVariant", getCurrentFile, notify=currentFileChanged)

    isPlaying = Property(bool, lambda self: self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState, notify=playStateChanged)

    # -- 检索槽 ------------------------------------------------------------

    @Slot(str, str, int)
    def doSearch(self, text: str, mode: str, limit: int = 50) -> None:
        text = text.strip()
        if not text:
            return
        self.setSearching(True)
        self._searchReq.emit(text, mode, limit)

    @Slot(str, int)
    def doSimilar(self, audio_path: str, limit: int = 50) -> None:
        self.setSearching(True)
        self._similarReq.emit(audio_path, limit)

    @Slot()
    def refreshStats(self) -> None:
        self._statsReq.emit()

    def _on_search_finished(self, items: list) -> None:
        self.setSearching(False)
        self.searchFinished.emit(items)

    # -- UCS 分类浏览 ------------------------------------------------------

    def getUcsModel(self) -> QObject:
        return self._ucs_model

    ucsModel = Property(QObject, getUcsModel, notify=ucsTreeChanged)

    def getUcsModelCount(self) -> int:
        return self._ucs_model.rowCount()

    ucsModelCount = Property(int, getUcsModelCount, notify=ucsTreeChanged)

    @Slot()
    def refreshUcsTree(self) -> None:
        """重新加载 UCS 树（打标推进后计数会变，点刷新即可）。"""
        self._ucsTreeReq.emit()

    @Slot(str)
    def browseUcs(self, catid: str) -> None:
        """点选叶子分类 → 列出该 CatID 下置信度最高的文件。"""
        if not catid:
            return
        self.setSearching(True)
        self._browseUcsReq.emit(catid, 60)

    def _on_ucs_tree_data(self, roots: list) -> None:
        model = UcsTreeModel(list(roots))
        model.setParent(self)
        self._ucs_model = model
        self.ucsTreeChanged.emit()

    def _on_browse_finished(self, items: list) -> None:
        self.setSearching(False)
        self.browseFinished.emit(items)

    # -- UCS 人工改标（写回，独立短连接 + busy_timeout + WAL） -------------

    def _ensure_catid_map(self) -> dict[str, dict]:
        if self._catid_map is None:
            self._catid_map = load_catid_map(self._ucs_dir)
        return self._catid_map

    @Slot(int, str, result=str)
    def setUcsLabel(self, file_id: int, catid: str) -> str:
        """人工改标：把 UCS 分类写回 ``ucs_labels``（source=manual）并重建标签。

        安全写锁方案落地：不走 UI 常驻只读连接，另开**短连接**（WAL + FK +
        busy_timeout=5s），写完 commit + close 即释放；与扫描子进程写锁竞争时
        SQLite 自动排队，不抛 database is locked。写后刷新树计数。
        """
        catid = (catid or "").strip()
        file_id = int(file_id or 0)
        if file_id <= 0:
            return "没有可改标的文件（fileId 缺失）"
        if not self._db_path.exists():
            return "索引库不存在：请先运行 soundcatcher scan 建立索引"
        catid_map = self._ensure_catid_map()
        if catid and catid not in catid_map:
            return f"未知 UCS 分类：{catid}"
        try:
            def _do() -> dict:
                conn = _connect_writer(self._db_path)
                try:
                    return apply_ucs_relabel(conn, catid_map, file_id, catid)
                finally:
                    conn.close()
            summary = _write_with_retry(_do)
        except Exception as exc:  # noqa: BLE001
            logger.exception("setUcsLabel 写回失败")
            return f"改标失败：{exc}"
        self.refreshUcsTree()   # 树计数随 manual 标签变化
        return f"已改标 #{file_id} → {summary['title']}（source=manual）"

    # -- UCS 扁平目录（分类选择 Popup 用） --------------------------------

    def getUcsCatalogList(self) -> list[dict]:
        if self._catalog_list is None:
            self._catalog_list = flat_catalog_list(self._ucs_dir)
        return self._catalog_list

    ucsCatalogList = Property("QVariant", getUcsCatalogList, notify=ucsTreeChanged)

    # -- 后台扫描任务（独立写者子进程，GUI 只读共存） -------------------------

    def getScanState(self) -> str:
        return self._scan_state

    scanState = Property(str, getScanState, notify=scanStateChanged)

    def getScanMessage(self) -> str:
        return self._scan_message

    scanMessage = Property(str, getScanMessage, notify=scanStateChanged)

    @Slot(str, result=str)
    def startScan(self, dir_path: str) -> str:
        """启动后台扫描子进程（``soundcatcher scan``）。

        护栏（坑 11 / 决策 4）：
        - 自身已有扫描在跑 → 拒绝；目标目录须存在。
        - 检测 data/ 下其他扫描写者的 pid 文件（gui_scan / scan_runner / scan_full），
          存活则拒绝，避免并发写同一 SQLite。
        - 子进程独立写库；GUI 只读连接（WAL 多读一写）与之安全共存。
        """
        dir_path = (dir_path or "").strip().strip("\"'")
        if not dir_path:
            return "请输入要扫描的目录路径"
        target = Path(dir_path)
        if not target.is_dir():
            return f"目录不存在：{dir_path}"
        if self._scan_proc is not None and self._scan_proc.poll() is None:
            return "已有扫描任务在运行（先等待完成或点 Stop（停止））"
        for pid_file in (
            self._scan_pid,
            self._scan_data_home / "scan_runner.pid",
            self._scan_data_home / "scan_full.pid",
        ):
            if pid_file.exists():
                try:
                    pid = int(pid_file.read_text(encoding="utf-8").strip().split()[0])
                except (OSError, ValueError):
                    continue
                if _pid_alive(pid):
                    return f"检测到其他扫描进程 (pid={pid})，避免并发写库（坑 11）"

        self._scan_data_home.mkdir(parents=True, exist_ok=True)
        logf = self._scan_log.open("w", encoding="utf-8")
        args = [sys.executable, "-m", "soundcatcher.cli", "scan", str(target)]
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            proc = subprocess.Popen(
                args, stdout=logf, stderr=subprocess.STDOUT,
                creationflags=flags, cwd=str(self._scan_data_home.parent),
            )
        except OSError as exc:
            logf.close()
            return f"启动扫描子进程失败：{exc}"
        self._scan_pid.write_text(str(proc.pid), encoding="utf-8")
        self._scan_proc = proc
        self._scan_state = "running"
        self._scan_stopping = False
        self._scan_target = target.name or str(target)
        self._scan_message = f"扫描中：{self._scan_target}（子进程 pid={proc.pid}）"
        self.scanStateChanged.emit()
        return self._scan_message

    @Slot(result=str)
    def stopScan(self) -> str:
        """终止扫描子进程。坑 9 已自愈：faiss 原子写 + 先 faiss 后 DB，被杀只留
        尾部批次，下次扫描自动补齐——因此强杀可接受。"""
        if self._scan_proc is None or self._scan_proc.poll() is not None:
            if self._scan_state != "idle":
                self._scan_state = "idle"
                self._scan_message = ""
                self.scanStateChanged.emit()
            return "当前没有运行中的扫描任务"
        try:
            self._scan_proc.terminate()   # Windows: TerminateProcess
            self._scan_stopping = True
            self._scan_message = "已请求停止（进程终止中；尾部批次由下次扫描自愈补齐）"
        except OSError as exc:
            self._scan_message = f"停止失败：{exc}"
        self.scanStateChanged.emit()
        return self._scan_message

    _PROGRESS_RE = None  # 惰性编译（re 模块在方法体外导入避免顶部开销）

    def _read_scan_progress(self) -> str:
        """运行中读日志尾部，解析 rich 进度行 `done/total` → 进度摘要。"""
        import re
        try:
            text = self._scan_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        if self._PROGRESS_RE is None:
            # 匹配 rich 输出的 `123/4567`（进度列最后一组数字对）
            type(self)._PROGRESS_RE = re.compile(r"(\d+)/(\d+)")
        hits = self._PROGRESS_RE.findall(text)
        if not hits:
            return ""
        done, total = int(hits[-1][0]), int(hits[-1][1])
        pct = f"{done * 100.0 / total:.1f}%" if total else "?"
        return f"{done}/{total}（{pct}）"

    def _tick_scan(self) -> None:
        """2s 轮询：子进程退出 → 读日志摘要 → 置终态；运行中 → 报实时进度。"""
        if self._scan_proc is None:
            return
        rc = self._scan_proc.poll()
        if rc is None:
            # 运行中：更新实时进度（仅变化时发信号，避免每 2s 刷屏）
            prog = self._read_scan_progress()
            if prog and prog != self._scan_message:
                self._scan_message = f"扫描中：{self._scan_target} {prog}"
                self.scanStateChanged.emit()
            return
        self._scan_proc = None
        tail = ""
        try:
            lines = self._scan_log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = next(
                (ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith("%")),
                "",
            )[:220]
        except OSError:
            pass
        if self._scan_stopping:
            self._scan_state = "done"
            self._scan_message = f"扫描已停止（尾部批次由下次扫描自愈补齐）：{tail}"
        else:
            self._scan_state = "done" if rc == 0 else "failed"
            self._scan_message = (
                f"扫描完成（exit {rc}）：{tail}" if rc == 0 else f"扫描异常（exit {rc}）：{tail}"
            )
        try:
            self._scan_pid.unlink()
        except OSError:
            pass
        self.scanStateChanged.emit()

    # -- 收藏（Favorites）----------------------------------------------------

    def getFavorites(self) -> list[dict]:
        return self._user.favorites

    favorites = Property("QVariant", getFavorites, notify=favoritesChanged)

    @Slot(str, result=bool)
    def isFavorite(self, path: str) -> bool:
        return self._user.is_favorite(path)

    @Slot(str, str, int, result=bool)
    def toggleFavorite(self, path: str, filename: str, file_id: int) -> bool:
        fav = self._user.toggle_favorite(path, filename, file_id or None)
        self.favoritesChanged.emit()
        return fav

    @Slot(str, result=bool)
    def removeFavorite(self, path: str) -> bool:
        ok = self._user.remove_favorite(path)
        if ok:
            self.favoritesChanged.emit()
        return ok

    # -- 收藏夹导出 ------------------------------------------------------

    @Slot(str, result=str)
    def exportFavorites(self, fmt: str = "md") -> str:
        """把收藏夹导出到 Downloads（`SOUNDCATCHER_EXPORT_DIR` 可覆盖），返回结果消息。"""
        try:
            out = self._user.export_favorites(_export_dir(), fmt or "md")
            n = len(self._user.favorites)
            return f"已导出 {n} 条收藏 → {out}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("收藏夹导出失败")
            return f"导出失败：{exc}"

    @Slot(str, result=str)
    def importFavorites(self, path: str) -> str:
        """从导出文件（md/csv/m3u）或纯路径列表导入收藏；返回统计消息。"""
        path = (path or "").strip()
        if not path:
            return "请选择要导入的收藏文件"
        try:
            n = self._user.import_favorites(path)
            self.favoritesChanged.emit()
            total = len(self._user.favorites)
            if n == 0:
                return f"文件可读但未解析出新收藏（现有 {total} 条不变）：{path}"
            return f"已导入 {n} 条新收藏（共 {total} 条）← {path}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("收藏导入失败")
            return f"导入失败：{exc}"

    # -- B5：来源文件夹管理（sources 表）-----------------------------------

    def getSources(self) -> list[dict]:
        """登记的来源文件夹列表（path/addedAt/lastScan）。读失败返回空表，不崩界面。"""
        if not self._db_path.exists():
            return []
        try:
            conn = _connect_readonly(self._db_path)
        except Exception:  # noqa: BLE001
            return []
        try:
            rows = conn.execute(
                "SELECT path, added_at, last_scan FROM sources ORDER BY added_at ASC"
            ).fetchall()
            return [
                {"path": r["path"], "addedAt": r["added_at"] or "", "lastScan": r["last_scan"] or ""}
                for r in rows
            ]
        except sqlite3.OperationalError:
            # 旧库尚未迁移出 sources 表 → 视作空表（不报错）
            return []
        finally:
            conn.close()

    sources = Property("QVariant", getSources, notify=sourcesChanged)

    @Slot(str, result=str)
    def addSource(self, path: str) -> str:
        """登记一个来源文件夹（去重）；返回给状态栏的提示。"""
        raw = (path or "").strip()
        if not raw:
            return "请选择要登记的文件夹"
        p = Path(raw)
        if not p.is_dir():
            return f"目录不存在或不可读：{raw}"
        norm = str(p.resolve())
        try:
            conn = _connect_writer(self._db_path)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sources WHERE path=?", (norm,)
                ).fetchone()
                if exists:
                    return f"该文件夹已在登记表中：{norm}"
                conn.execute(
                    "INSERT INTO sources(path, added_at, last_scan) VALUES(?, ?, '')",
                    (norm, time.strftime("%Y-%m-%d %H:%M")),
                )
                conn.commit()
            finally:
                conn.close()
            self.sourcesChanged.emit()
            return f"已登记来源：{norm}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("登记来源失败")
            return f"登记失败：{exc}"

    @Slot(str, result=str)
    def removeSource(self, path: str) -> str:
        """从登记表移除（**不删任何文件**）；返回给状态栏的提示。"""
        raw = (path or "").strip()
        if not raw:
            return "未指定来源"
        try:
            conn = _connect_writer(self._db_path)
            try:
                conn.execute("DELETE FROM sources WHERE path=?", (raw,))
                conn.commit()
            finally:
                conn.close()
            self.sourcesChanged.emit()
            return f"已移除来源：{raw}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("移除来源失败")
            return f"移除失败：{exc}"

    @Slot(result=str)
    def scanAllSources(self) -> str:
        """依次对每个登记来源启动扫描（同一条后台子进程链路；运行中拒绝重复启动）。"""
        srcs = self.getSources()
        if not srcs:
            return "尚未登记来源文件夹"
        started = 0
        last = ""
        for s in srcs:
            msg = self.startScan(s["path"])
            last = msg
            # startScan 成功时返回 "扫描中：…"；被拒绝时返回其他文案 → 只在成功时计数
            if msg.startswith("扫描中"):
                started += 1
            else:
                break
        if started <= 1:
            return last
        return f"已开始扫描 {started} 个来源文件夹"

    # -- 保存搜索（Saved Searches）------------------------------------------

    def getSavedSearches(self) -> list[dict]:
        return self._user.saved_searches

    savedSearches = Property("QVariant", getSavedSearches, notify=savedSearchesChanged)

    @Slot(str, str)
    def saveSearch(self, query: str, mode: str) -> None:
        self._user.add_saved_search(query, mode)
        self.savedSearchesChanged.emit()

    @Slot(str, str, result=bool)
    def removeSavedSearch(self, query: str, mode: str) -> bool:
        ok = self._user.remove_saved_search(query, mode)
        if ok:
            self.savedSearchesChanged.emit()
        return ok

    # -- 播放槽 ------------------------------------------------------------

    @Slot(str, str)
    def playFile(self, path: str, filename: str) -> None:
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self._set_current(dict(fileId=-1, path=path, filename=filename))

    @Slot()
    def togglePlay(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    @Slot()
    def stopPlay(self) -> None:
        self.player.stop()

    @Slot(int)
    def seekTo(self, ms: int) -> None:
        self.player.setPosition(ms)

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            name = "playing"
        elif state == QMediaPlayer.PlaybackState.PausedState:
            name = "paused"
        else:
            name = "stopped"
        self.playStateChanged.emit(name)

    def _set_current(self, info: dict) -> None:
        self._current_file = info
        self._current_waveform = None
        self.currentFileChanged.emit()

    # -- 波形槽 ------------------------------------------------------------

    @Slot(int, str)
    def loadWaveform(self, file_id: int, path: str) -> None:
        self._wave_service.load(file_id, path)

    def _on_waveform_ready(self, file_id: int, peaks: list) -> None:
        self._current_waveform = peaks
        self.waveformReady.emit(file_id, peaks)

    def _on_waveform_failed(self, _file_id: int, msg: str) -> None:
        self.searchFailed.emit(f"波形解码失败：{msg}")

    def getCurrentWaveform(self) -> list[float] | None:
        return self._current_waveform

    currentWaveform = Property("QVariant", getCurrentWaveform, notify=waveformReady)

    # -- 音量 --------------------------------------------------------------

    @Slot(float)
    def setVolume(self, v: float) -> None:
        self.audio_output.setVolume(v)

    def getVolume(self) -> float:
        return self.audio_output.volume()

    volume = Property(float, getVolume, setVolume)

    def _on_volume(self, _v: float) -> None:
        pass

    # -- 播放位置辅助 ------------------------------------------------------

    @Slot(result=int)
    def playbackPosition(self) -> int:
        return self.player.position()

    @Slot(result=int)
    def playbackDuration(self) -> int:
        return self.player.duration()

    # -- 生命周期 ----------------------------------------------------------

    @Slot()
    def shutdown(self) -> None:
        """退出清理：停轮询、停播放、等两个工作线程结束。

        扫描子进程**不杀**：独立写者，GUI 退出后继续跑（同 run_scan 守护理念）；
        下次启动会通过 pid 文件检测到它并拒绝重复启动。
        """
        self._stats_timer.stop()
        self._scan_timer.stop()
        self.player.stop()
        self._wave_thread.quit()
        self._model_thread.quit()
        self._wave_thread.wait(3000)
        self._model_thread.wait(5000)