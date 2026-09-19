"""向量索引与扫描管线。

**索引策略（10 万级定稿）**：使用 faiss ``IndexIDMap2(IndexFlatIP)`` —— 内积精确检索。
向量已 L2 归一化，内积即余弦相似度。

为什么阶段 1 用精确检索而非 IVF/HNSW：10 万 × 512 维的 flat 检索在 faiss（SIMD/BLAS
加速）下是毫秒级，且召回率 100%，没有近似损失。当库规模逼近百万级时，再把
``VectorIndex`` 切换到 ``IndexIVFFlat`` / ``IndexHNSW`` —— 接口不变，只换内部实现。

向量 id 直接复用 SQLite 的 ``files.id``，两者一一对应；删除/更新文件时先移除旧向量。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import faiss
import numpy as np

from . import db
from .audio import load_for_embedding, probe
from .embedder import ClapEmbedder

logger = logging.getLogger(__name__)

DIM = 512

# 主流音频格式（全格式经 ffmpeg 解码，这里只决定"哪些文件纳入扫描"）
AUDIO_EXTS: frozenset[str] = frozenset(
    {
        # 无损 / 专业
        ".wav", ".wave", ".bwf", ".rf64", ".w64",
        ".aif", ".aiff", ".aifc",
        ".flac", ".caf", ".sd2",
        ".ape", ".wv", ".mpc", ".tta", ".au", ".snd",
        # 有损 / 交付
        ".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus",
        ".wma", ".amr", ".ac3", ".dts", ".mka",
        # 视频容器（只取音轨）
        ".mp4", ".mov", ".mkv", ".webm", ".avi",
    }
)


# ---------------------------------------------------------------------------
# faiss 索引封装
# ---------------------------------------------------------------------------


class VectorIndex:
    """faiss 向量索引（内积 / 余弦），支持增量增删与落盘。"""

    def __init__(self, path: str | Path, dim: int = DIM):
        self.path = Path(path)
        self.dim = dim
        if self.path.exists():
            self.index = faiss.read_index(str(self.path))
            logger.info("载入已有向量索引：%d 条", self.index.ntotal)
        else:
            self.index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))

    def __len__(self) -> int:
        return int(self.index.ntotal)

    def add(self, vectors: np.ndarray, ids: Iterable[int]) -> None:
        vecs = np.ascontiguousarray(vectors, dtype=np.float32)
        id_arr = np.asarray(list(ids), dtype=np.int64)
        if vecs.shape[0] != id_arr.size:
            raise ValueError(f"向量数({vecs.shape[0]})与 id 数({id_arr.size})不一致")
        self.index.add_with_ids(vecs, id_arr)

    def remove(self, ids: Iterable[int]) -> int:
        id_arr = np.asarray(list(ids), dtype=np.int64)
        if id_arr.size == 0:
            return 0
        return int(self.index.remove_ids(id_arr))

    def search(self, query: np.ndarray, k: int = 20) -> tuple[np.ndarray, np.ndarray]:
        """返回 ``(ids, scores)``，按相似度降序。"""
        q = np.ascontiguousarray(query.reshape(1, -1), dtype=np.float32)
        scores, ids = self.index.search(q, k)
        return ids[0].astype(np.int64), scores[0].astype(np.float32)

    def search_batch(self, queries: np.ndarray, k: int = 20) -> tuple[np.ndarray, np.ndarray]:
        q = np.ascontiguousarray(queries, dtype=np.float32)
        scores, ids = self.index.search(q, k)
        return ids.astype(np.int64), scores.astype(np.float32)

    def vectors_by_id(self, ids: Iterable[int]) -> np.ndarray:
        """按文件 id 批量重建向量 → ``(N, dim)``（行序同传入 ids）。

        UCS 分类等下游直接消费已嵌入向量，无需重新解码音频。
        """
        id_arr = list(ids)
        if not id_arr:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self.index.reconstruct(int(i)) for i in id_arr])

    def save(self) -> None:
        """原子落盘：先写同目录 ``.tmp``，成功后 ``os.replace`` 改名。

        避免进程被强杀在 ``faiss.write_index`` 中途时把正式文件写坏；
        NTFS 的 rename 是原子的——磁盘上永远只有「旧完整文件」或「新完整文件」。
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        faiss.write_index(self.index, str(tmp))
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------


def iter_audio_files(roots: Iterable[str | Path], exts: frozenset[str] = AUDIO_EXTS) -> Iterator[Path]:
    """递归遍历给定根目录下的所有音频文件。"""
    for root in roots:
        base = Path(root)
        if base.is_file():
            if base.suffix.lower() in exts:
                yield base
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                yield p


@dataclass
class ScanStats:
    """一次扫描的结果统计。"""

    total: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"扫描 {self.total} 个文件：新增 {self.added}、更新 {self.updated}、"
            f"跳过 {self.skipped}、失败 {self.failed}，索引共 {self.embedded_total} 条"
        )

    embedded_total: int = 0


ProgressCb = Callable[[int, int, str], None]


class Indexer:
    """把音频文件变成「SQLite 元数据 + faiss 向量」。"""

    def __init__(
        self,
        conn,
        index: VectorIndex,
        embedder: ClapEmbedder,
        *,
        batch_size: int = 16,
        commit_every: int = 200,
    ):
        self.conn = conn
        self.index = index
        self.embedder = embedder
        self.batch_size = batch_size
        self.commit_every = commit_every

    # -- 单文件判定 --------------------------------------------------------

    def _is_current(self, path: Path, stat) -> bool:
        row = db.get_file_by_path(self.conn, str(path))
        if row is None:
            return False
        # 坏文件黑名单：error 非空且 mtime/size 未变 → 视为已处理，跳过（避免每轮全量重试）
        if row["error"] is not None:
            if row["size"] != stat.st_size:
                return False
            return abs(float(row["mtime"]) - stat.st_mtime) < 1e-6
        if row["embedded"] != 1:
            return False
        if row["size"] != stat.st_size:
            return False
        return abs(float(row["mtime"]) - stat.st_mtime) < 1e-6

    # -- 主流程 ------------------------------------------------------------

    def scan(
        self,
        roots: Iterable[str | Path],
        *,
        progress: ProgressCb | None = None,
        is_new_hint: bool = True,
    ) -> ScanStats:
        """扫描目录并增量索引。

        Args:
            roots: 要扫描的根目录（或单个文件）。
            progress: 进度回调 ``(done, total, current_path)``。
        """
        files = list(iter_audio_files(roots))
        stats = ScanStats(total=len(files))
        stats.embedded_total = len(self.index)

        pending: list[tuple[int, Path, np.ndarray]] = []
        seen_since_commit = 0

        def flush() -> None:
            if not pending:
                return
            ids = [fid for fid, _, _ in pending]
            wavs = [w for _, _, w in pending]
            try:
                vectors = self.embedder.embed_audio_batch(wavs)
            except Exception as exc:  # 批量失败则逐个降级，定位坏样本
                logger.warning("批量嵌入失败，逐条重试：%s", exc)
                for fid, p, w in list(pending):
                    try:
                        v = self.embedder.embed_audio(w)
                        self.index.remove([fid])
                        self.index.add(v[None, :], [fid])
                        db.mark_embedded(self.conn, fid, True)
                    except Exception as inner:
                        db.mark_embedded(self.conn, fid, False, str(inner))
                        stats.errors.append((str(p), str(inner)))
                        stats.failed += 1
                pending.clear()
                return

            self.index.remove(ids)  # 幂等：清掉可能存在的旧向量
            self.index.add(vectors, ids)
            for fid, _, _ in pending:
                db.mark_embedded(self.conn, fid, True)
            pending.clear()

        for i, path in enumerate(files, start=1):
            if progress is not None and (i == 1 or i % 25 == 0 or i == len(files)):
                progress(i, len(files), str(path))

            try:
                stat = path.stat()
            except OSError as exc:
                stats.failed += 1
                stats.errors.append((str(path), f"stat 失败：{exc}"))
                continue

            if is_new_hint and self._is_current(path, stat):
                stats.skipped += 1
                continue

            existed = db.get_file_by_path(self.conn, str(path)) is not None

            try:
                info = probe(path)
                wav = load_for_embedding(path)
            except Exception as exc:
                file_id = db.upsert_file(
                    self.conn,
                    path=str(path),
                    filename=path.name,
                    ext=path.suffix.lower().lstrip("."),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
                db.mark_embedded(self.conn, file_id, False, f"解码失败：{exc}")
                stats.failed += 1
                stats.errors.append((str(path), str(exc)))
                continue

            file_id = db.upsert_file(
                self.conn,
                path=str(path),
                filename=path.name,
                ext=path.suffix.lower().lstrip("."),
                size=stat.st_size,
                mtime=stat.st_mtime,
                duration=info.duration,
                sample_rate=info.sample_rate,
                channels=info.channels,
                codec=info.codec,
                fmt=info.format,
            )
            if existed:
                stats.updated += 1
            else:
                stats.added += 1

            pending.append((file_id, path, wav))
            if len(pending) >= self.batch_size:
                flush()
                self.index.save()  # 先落 faiss：即使随后被杀，DB 也尚未声称这批已嵌入
                self.conn.commit()
                stats.embedded_total = len(self.index)
                seen_since_commit = 0
            else:
                seen_since_commit += 1
                if seen_since_commit >= self.commit_every:
                    self.conn.commit()
                    seen_since_commit = 0

        flush()
        self.index.save()
        self.conn.commit()
        stats.embedded_total = len(self.index)
        return stats
